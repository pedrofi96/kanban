"""
Testes das regras de card.

    python manage.py test kanban

O Django cria um banco TEMPORÁRIO só para os testes e apaga no final:
os dados de verdade não são tocados.
"""

import json

from django.test import TestCase

from usuarios.models import Andar, Usuario

from . import services
from .models import Card, MembroQuadro

Cargo = Usuario.Cargo


def criar_usuario(username, andar, cargo=Cargo.USUARIO):
    return Usuario.objects.create_user(
        username=username,
        password="123",
        email=f"{username}@salvador.ba.gov.br",
        first_name=username.capitalize(),
        andar=andar,
        cargo=cargo,
    )


class RegrasDeCardTests(TestCase):
    """Quem pode excluir cards e mudar a data de vencimento."""

    @classmethod
    def setUpTestData(cls):
        # Os 5 andares já existem: a migration de dados roda no banco de teste.
        andar1 = Andar.objects.get(numero=1)
        andar2 = Andar.objects.get(numero=2)

        cls.admin_geral = criar_usuario("geral", andar1, Cargo.ADMIN_GERAL)
        cls.admin_do_andar = criar_usuario("admin2", andar2, Cargo.ADMIN_ANDAR)   # andar do projeto
        cls.admin_de_fora = criar_usuario("admin1", andar1, Cargo.ADMIN_ANDAR)    # outro andar, mas membro
        cls.usuario = criar_usuario("servidor", andar2)                           # usuário normal, membro
        cls.estranho = criar_usuario("estranho", andar2)                          # não é membro

        # Projeto do 2º andar.
        cls.quadro = services.criar_quadro("Projeto de teste", andar2, cls.admin_do_andar)
        for membro in (cls.admin_de_fora, cls.usuario):
            MembroQuadro.objects.create(quadro=cls.quadro, usuario=membro)
        cls.coluna = cls.quadro.colunas.first()

    def setUp(self):
        self.card = Card.objects.create(coluna=self.coluna, titulo="Card", vencimento="2026-12-01")
        self.url = f"/api/cards/{self.card.pk}/"

    # ---------- auxiliares ----------

    def como(self, usuario):
        self.client.force_login(usuario)
        return self.client

    def patch(self, usuario, dados):
        return self.como(usuario).patch(self.url, json.dumps(dados), content_type="application/json")

    def criar(self, usuario, dados):
        dados = {"coluna_id": self.coluna.pk, **dados}
        return self.como(usuario).post("/api/cards/", json.dumps(dados), content_type="application/json")

    # ---------- criar card ----------

    def test_usuario_normal_cria_card_com_data(self):
        resposta = self.criar(self.usuario, {"titulo": "Novo", "vencimento": "2026-12-24"})
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()["vencimento"], "2026-12-24")

    def test_criar_card_sem_data_continua_funcionando(self):
        resposta = self.criar(self.usuario, {"titulo": "Novo"})
        self.assertEqual(resposta.status_code, 201)
        self.assertIsNone(resposta.json()["vencimento"])

    def test_data_em_formato_errado_e_recusada(self):
        resposta = self.criar(self.usuario, {"titulo": "Novo", "vencimento": "24/12/2026"})
        self.assertEqual(resposta.status_code, 400)

    def test_quem_nao_e_membro_nao_cria_card(self):
        self.assertEqual(self.criar(self.estranho, {"titulo": "Novo"}).status_code, 403)

    # ---------- data de vencimento ----------

    def test_usuario_normal_nao_muda_a_data(self):
        self.assertEqual(self.patch(self.usuario, {"vencimento": "2026-12-25"}).status_code, 403)
        self.assertEqual(self.patch(self.usuario, {"vencimento": None}).status_code, 403)
        self.card.refresh_from_db()
        self.assertEqual(self.card.vencimento.isoformat(), "2026-12-01")

    def test_usuario_normal_edita_o_resto_do_card(self):
        resposta = self.patch(self.usuario, {"titulo": "Outro título", "descricao": "x", "prioridade": "alta"})
        self.assertEqual(resposta.status_code, 200)

    def test_reenviar_a_mesma_data_nao_da_erro(self):
        # O "Salvar mudanças" pode mandar todos os campos, inclusive a data que não mudou.
        resposta = self.patch(self.usuario, {"titulo": "Outro título", "vencimento": "2026-12-01"})
        self.assertEqual(resposta.status_code, 200)

    def test_admin_do_andar_do_projeto_muda_a_data(self):
        self.assertEqual(self.patch(self.admin_do_andar, {"vencimento": "2026-12-25"}).status_code, 200)
        self.card.refresh_from_db()
        self.assertEqual(self.card.vencimento.isoformat(), "2026-12-25")

    def test_admin_geral_muda_a_data(self):
        self.assertEqual(self.patch(self.admin_geral, {"vencimento": None}).status_code, 200)

    def test_admin_de_outro_andar_nao_muda_a_data(self):
        # É admin do andar, mas de OUTRO andar: aqui ele é só um membro.
        self.assertEqual(self.patch(self.admin_de_fora, {"vencimento": "2026-12-25"}).status_code, 403)

    # ---------- excluir card ----------

    def test_usuario_normal_nao_exclui_card(self):
        self.assertEqual(self.como(self.usuario).delete(self.url).status_code, 403)
        self.assertTrue(Card.objects.filter(pk=self.card.pk).exists())

    def test_admin_de_outro_andar_nao_exclui_card(self):
        self.assertEqual(self.como(self.admin_de_fora).delete(self.url).status_code, 403)
        self.assertTrue(Card.objects.filter(pk=self.card.pk).exists())

    def test_admin_do_andar_do_projeto_exclui_card(self):
        self.assertEqual(self.como(self.admin_do_andar).delete(self.url).status_code, 200)
        self.assertFalse(Card.objects.filter(pk=self.card.pk).exists())

    def test_admin_geral_exclui_card(self):
        self.assertEqual(self.como(self.admin_geral).delete(self.url).status_code, 200)

    # ---------- flags enviadas ao front ----------

    def flags(self, usuario):
        quadro = self.como(usuario).get("/api/estado/").json()["quadros"][0]
        return (quadro["pode_excluir_card"], quadro["pode_alterar_vencimento"], quadro["pode_gerenciar_colunas"])

    def test_flags_do_estado(self):
        self.assertEqual(self.flags(self.usuario), (False, False, False))
        self.assertEqual(self.flags(self.admin_de_fora), (False, False, False))
        self.assertEqual(self.flags(self.admin_do_andar), (True, True, True))
        self.assertEqual(self.flags(self.admin_geral), (True, True, True))


class RegrasDeColunaTests(TestCase):
    """Criar, renomear e excluir colunas."""

    @classmethod
    def setUpTestData(cls):
        andar1 = Andar.objects.get(numero=1)
        andar2 = Andar.objects.get(numero=2)

        cls.admin_geral = criar_usuario("geral", andar1, Cargo.ADMIN_GERAL)
        cls.admin_do_andar = criar_usuario("admin2", andar2, Cargo.ADMIN_ANDAR)
        cls.admin_de_fora = criar_usuario("admin1", andar1, Cargo.ADMIN_ANDAR)
        cls.usuario = criar_usuario("servidor", andar2)

        # Projeto do 2º andar, com as 4 colunas padrão.
        cls.quadro = services.criar_quadro("Projeto de teste", andar2, cls.admin_do_andar)
        for membro in (cls.admin_de_fora, cls.usuario):
            MembroQuadro.objects.create(quadro=cls.quadro, usuario=membro)

    # ---------- auxiliares ----------

    def como(self, usuario):
        self.client.force_login(usuario)
        return self.client

    def titulos(self):
        return list(self.quadro.colunas.values_list("titulo", flat=True))

    def coluna(self, titulo):
        return self.quadro.colunas.get(titulo=titulo)

    def criar(self, usuario, titulo):
        return self.como(usuario).post(
            f"/api/quadros/{self.quadro.pk}/colunas/", json.dumps({"titulo": titulo}), content_type="application/json"
        )

    def renomear(self, usuario, coluna, titulo):
        return self.como(usuario).patch(
            f"/api/colunas/{coluna.pk}/", json.dumps({"titulo": titulo}), content_type="application/json"
        )

    def excluir(self, usuario, coluna):
        return self.como(usuario).delete(f"/api/colunas/{coluna.pk}/")

    # ---------- quem pode ----------

    def test_usuario_normal_nao_mexe_em_colunas(self):
        coluna = self.coluna("Em Revisão")
        self.assertEqual(self.criar(self.usuario, "Nova").status_code, 403)
        self.assertEqual(self.renomear(self.usuario, coluna, "Outro nome").status_code, 403)
        self.assertEqual(self.excluir(self.usuario, coluna).status_code, 403)
        self.assertEqual(self.titulos(), ["A Fazer", "Em Progresso", "Em Revisão", "Concluído"])

    def test_admin_de_outro_andar_nao_mexe_em_colunas(self):
        coluna = self.coluna("Em Revisão")
        self.assertEqual(self.criar(self.admin_de_fora, "Nova").status_code, 403)
        self.assertEqual(self.renomear(self.admin_de_fora, coluna, "Outro nome").status_code, 403)
        self.assertEqual(self.excluir(self.admin_de_fora, coluna).status_code, 403)

    def test_admin_geral_mexe_em_colunas(self):
        self.assertEqual(self.criar(self.admin_geral, "Nova").status_code, 200)
        self.assertEqual(self.excluir(self.admin_geral, self.coluna("Nova")).status_code, 200)

    # ---------- criar ----------

    def test_coluna_nova_entra_antes_da_concluido(self):
        resposta = self.criar(self.admin_do_andar, "Homologação")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.titulos(), ["A Fazer", "Em Progresso", "Em Revisão", "Homologação", "Concluído"])
        # A resposta traz a lista inteira, já na ordem, sem buracos.
        self.assertEqual([c["ordem"] for c in resposta.json()["colunas"]], [0, 1, 2, 3, 4])
        self.assertTrue(resposta.json()["colunas"][-1]["concluida"])

    def test_nome_vazio_ou_repetido_e_recusado(self):
        self.assertEqual(self.criar(self.admin_do_andar, "   ").status_code, 400)
        self.assertEqual(self.criar(self.admin_do_andar, "a fazer").status_code, 400)
        self.assertEqual(self.criar(self.admin_do_andar, "concluído").status_code, 400)
        self.assertEqual(len(self.titulos()), 4)

    # ---------- renomear ----------

    def test_admin_renomeia_coluna(self):
        self.assertEqual(self.renomear(self.admin_do_andar, self.coluna("Em Revisão"), "Validação").status_code, 200)
        self.assertEqual(self.titulos(), ["A Fazer", "Em Progresso", "Validação", "Concluído"])

    def test_concluido_nao_pode_ser_renomeada(self):
        self.assertEqual(self.renomear(self.admin_geral, self.coluna("Concluído"), "Feito").status_code, 400)
        self.assertEqual(self.titulos()[-1], "Concluído")

    def test_renomear_para_nome_de_outra_coluna_e_recusado(self):
        self.assertEqual(self.renomear(self.admin_do_andar, self.coluna("Em Revisão"), "A Fazer").status_code, 400)

    # ---------- excluir ----------

    def test_admin_exclui_coluna_vazia(self):
        self.assertEqual(self.excluir(self.admin_do_andar, self.coluna("Em Progresso")).status_code, 200)
        self.assertEqual(self.titulos(), ["A Fazer", "Em Revisão", "Concluído"])
        self.assertEqual(list(self.quadro.colunas.values_list("ordem", flat=True)), [0, 1, 2])

    def test_coluna_com_card_nao_pode_ser_excluida(self):
        coluna = self.coluna("Em Progresso")
        Card.objects.create(coluna=coluna, titulo="Card")
        self.assertEqual(self.excluir(self.admin_do_andar, coluna).status_code, 400)
        self.assertEqual(len(self.titulos()), 4)

    def test_concluido_nao_pode_ser_excluida(self):
        self.assertEqual(self.excluir(self.admin_geral, self.coluna("Concluído")).status_code, 400)
        self.assertEqual(len(self.titulos()), 4)

    def test_projeto_fica_com_no_minimo_3_colunas(self):
        self.assertEqual(self.excluir(self.admin_do_andar, self.coluna("Em Progresso")).status_code, 200)
        # Agora são 3 (contando a "Concluído"): não dá para excluir mais nenhuma.
        self.assertEqual(self.excluir(self.admin_do_andar, self.coluna("Em Revisão")).status_code, 400)
        self.assertEqual(self.titulos(), ["A Fazer", "Em Revisão", "Concluído"])

    # ---------- mover ----------

    def test_mover_coluna_para_o_inicio(self):
        services.mover_coluna(self.coluna("Em Revisão"), 0)
        self.assertEqual(self.titulos(), ["Em Revisão", "A Fazer", "Em Progresso", "Concluído"])

    def test_coluna_nao_passa_da_concluido(self):
        services.mover_coluna(self.coluna("A Fazer"), 99)
        self.assertEqual(self.titulos(), ["Em Progresso", "Em Revisão", "A Fazer", "Concluído"])

    def test_concluido_nao_se_move(self):
        with self.assertRaises(services.RegraDeColuna):
            services.mover_coluna(self.coluna("Concluído"), 0)

    def test_posicao_invalida_e_recusada(self):
        with self.assertRaises(services.RegraDeColuna):
            services.mover_coluna(self.coluna("A Fazer"), "abc")

    def test_cards_vao_junto_com_a_coluna(self):
        coluna = self.coluna("Em Revisão")
        card = Card.objects.create(coluna=coluna, titulo="Card")
        services.mover_coluna(coluna, 0)
        card.refresh_from_db()
        self.assertEqual(card.coluna_id, coluna.pk)

    def mover(self, usuario, coluna, ordem):
        return self.como(usuario).post(
            f"/api/colunas/{coluna.pk}/mover/", json.dumps({"ordem": ordem}), content_type="application/json"
        )

    def test_admin_move_coluna_pela_api(self):
        resposta = self.mover(self.admin_do_andar, self.coluna("Em Revisão"), 0)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual([c["titulo"] for c in resposta.json()["colunas"]],
                         ["Em Revisão", "A Fazer", "Em Progresso", "Concluído"])

    def test_usuario_normal_nao_move_coluna(self):
        self.assertEqual(self.mover(self.usuario, self.coluna("Em Revisão"), 0).status_code, 403)
        self.assertEqual(self.titulos(), ["A Fazer", "Em Progresso", "Em Revisão", "Concluído"])

    def test_admin_de_outro_andar_nao_move_coluna(self):
        self.assertEqual(self.mover(self.admin_de_fora, self.coluna("Em Revisão"), 0).status_code, 403)

    def test_mover_concluido_pela_api_da_400(self):
        self.assertEqual(self.mover(self.admin_geral, self.coluna("Concluído"), 0).status_code, 400)
class SalvarMudancasTests(TestCase):
    """O "Salvar mudanças" do card: campos e checklist numa chamada só."""

    @classmethod
    def setUpTestData(cls):
        andar2 = Andar.objects.get(numero=2)
        cls.admin = criar_usuario("admin2", andar2, Cargo.ADMIN_ANDAR)
        cls.usuario = criar_usuario("servidor", andar2)
        cls.quadro = services.criar_quadro("Projeto de teste", andar2, cls.admin)
        MembroQuadro.objects.create(quadro=cls.quadro, usuario=cls.usuario)

    def setUp(self):
        self.card = Card.objects.create(coluna=self.quadro.colunas.first(), titulo="Card", vencimento="2026-12-01")
        self.manter = self.card.checklist.create(texto="Manter", feito=False, ordem=0)
        self.remover = self.card.checklist.create(texto="Remover", feito=False, ordem=1)

    def salvar(self, dados):
        self.client.force_login(self.usuario)
        return self.client.patch(f"/api/cards/{self.card.pk}/", json.dumps(dados), content_type="application/json")

    def checklist(self):
        return list(self.card.checklist.values_list("texto", "feito"))

    def test_checklist_e_campos_sao_salvos_juntos(self):
        resposta = self.salvar({
            "titulo": "Novo título",
            "checklist": [
                {"id": self.manter.pk, "texto": "Manter", "feito": True},   # marcado
                {"id": None, "texto": "Item novo", "feito": False},         # criado
            ],                                                              # "Remover" ficou de fora
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.checklist(), [("Manter", True), ("Item novo", False)])
        self.assertEqual([i["texto"] for i in resposta.json()["checklist"]], ["Manter", "Item novo"])
        self.card.refresh_from_db()
        self.assertEqual(self.card.titulo, "Novo título")

    def test_sem_checklist_no_pedido_os_itens_nao_mudam(self):
        self.assertEqual(self.salvar({"titulo": "Novo título"}).status_code, 200)
        self.assertEqual(self.checklist(), [("Manter", False), ("Remover", False)])

    def test_se_a_data_for_barrada_nada_e_salvo(self):
        # Usuário normal tenta mudar a data junto com o checklist: 403 e o checklist fica como estava.
        resposta = self.salvar({"vencimento": "2026-12-25", "checklist": []})
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(self.checklist(), [("Manter", False), ("Remover", False)])

    def test_id_de_item_de_outro_card_nao_altera_o_outro_card(self):
        outro = Card.objects.create(coluna=self.quadro.colunas.first(), titulo="Outro")
        alheio = outro.checklist.create(texto="Do outro card", feito=False)
        self.salvar({"checklist": [{"id": alheio.pk, "texto": "Invadido", "feito": True}]})
        alheio.refresh_from_db()
        self.assertEqual((alheio.texto, alheio.feito), ("Do outro card", False))

    def test_checklist_malformado_e_recusado(self):
        self.assertEqual(self.salvar({"checklist": "abc"}).status_code, 400)
        self.assertEqual(self.checklist(), [("Manter", False), ("Remover", False)])


class StatusDoProjetoTests(TestCase):
    """Projeto concluído = pelo menos 1 card e todos na coluna "Concluído"."""

    @classmethod
    def setUpTestData(cls):
        andar2 = Andar.objects.get(numero=2)
        cls.admin = criar_usuario("admin2", andar2, Cargo.ADMIN_ANDAR)
        cls.quadro = services.criar_quadro("Projeto de teste", andar2, cls.admin)
        cls.a_fazer = cls.quadro.colunas.get(titulo="A Fazer")
        cls.concluido = cls.quadro.colunas.get(concluida=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def post(self, url, dados):
        return self.client.post(url, json.dumps(dados), content_type="application/json")

    def criar(self, coluna, titulo="Card"):
        return self.post("/api/cards/", {"coluna_id": coluna.pk, "titulo": titulo}).json()["id"]

    def mover(self, card_id, coluna):
        return self.post(f"/api/cards/{card_id}/mover/", {"coluna_id": coluna.pk, "ordem": 0})

    def status(self):
        self.quadro.refresh_from_db()
        return self.quadro.concluido

    def test_projeto_sem_cards_nao_e_concluido(self):
        self.assertFalse(self.status())
        self.assertIsNone(self.quadro.concluido_em)

    def test_fica_concluido_quando_o_ultimo_card_chega_na_coluna_concluido(self):
        um, dois = self.criar(self.a_fazer), self.criar(self.a_fazer)
        self.mover(um, self.concluido)
        self.assertFalse(self.status())          # ainda falta um
        self.mover(dois, self.concluido)
        self.assertTrue(self.status())
        self.assertIsNotNone(self.quadro.concluido_em)

    def test_deixa_de_ser_concluido_quando_um_card_volta(self):
        card = self.criar(self.concluido)        # criado direto na "Concluído"
        self.assertTrue(self.status())
        self.mover(card, self.a_fazer)
        self.assertFalse(self.status())
        self.assertIsNone(self.quadro.concluido_em)

    def test_card_novo_em_outra_coluna_reabre_o_projeto(self):
        self.criar(self.concluido)
        self.assertTrue(self.status())
        self.criar(self.a_fazer)
        self.assertFalse(self.status())

    def test_excluir_o_card_pendente_conclui_o_projeto(self):
        self.criar(self.concluido)
        pendente = self.criar(self.a_fazer)
        self.assertFalse(self.status())
        self.client.delete(f"/api/cards/{pendente}/")
        self.assertTrue(self.status())

    def test_excluir_o_ultimo_card_tira_o_status(self):
        card = self.criar(self.concluido)
        self.assertTrue(self.status())
        self.client.delete(f"/api/cards/{card}/")
        self.assertFalse(self.status())

    def test_status_vai_no_estado_enviado_ao_front(self):
        self.criar(self.concluido)
        quadro = self.client.get("/api/estado/").json()["quadros"][0]
        self.assertTrue(quadro["concluido"])


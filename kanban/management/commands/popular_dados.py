"""
Dados de exemplo para desenvolvimento.

    venv\\Scripts\\python.exe manage.py popular_dados

- APAGA todos os projetos/cards e recria os de exemplo.
- Cria (ou atualiza) os usuários de exemplo abaixo, todos com a senha "123".
  O superuser (dev) não é mexido.
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from kanban.models import AtividadeCard, Card, ChecklistItem, MembroQuadro, Quadro
from usuarios.models import Andar, ConviteTransferencia, Usuario

SENHA = "123"
Cargo = Usuario.Cargo

# username: (nome, sobrenome, andar, cargo, deve_trocar_senha)
# O 4º andar fica vazio de propósito e o 5º fica sem administrador.
USUARIOS = {
    "gabriela": ("Gabriela", "Souza", 1, Cargo.ADMIN_GERAL, False),
    "ana": ("Ana", "Lima", 2, Cargo.ADMIN_ANDAR, False),
    "bruno": ("Bruno", "Costa", 2, Cargo.USUARIO, False),
    "novato": ("Novo", "Servidor", 2, Cargo.USUARIO, True),
    "carla": ("Carla", "Mendes", 3, Cargo.ADMIN_ANDAR, False),
    "arthur": ("Arthur", "Rocha", 3, Cargo.USUARIO, False),
    "elisa": ("Elisa", "Nunes", 5, Cargo.USUARIO, False),
}

# (coluna_idx, titulo, descricao, prioridade, responsavel, dias_ate_vencimento, checklist)
# dias negativos = vencido
QUADROS = {
    ("Projeto 1", 2, ("ana", "bruno", "arthur")): [
        (0, "Levantar requisitos do sistema", "Reunir com os setores do 2º andar para mapear as demandas.", "alta", "ana", -3,
         [("Agendar reunião", True), ("Montar questionário", False), ("Consolidar respostas", False)]),
        (0, "Definir identidade visual", "Escolher paleta de cores e tipografia do portal.", "baixa", "bruno", 12, []),
        (1, "Modelar banco de dados", "Criar diagrama ER com quadros, colunas e cards.", "alta", "bruno", 2,
         [("Entidades principais", True), ("Relacionamentos", True), ("Revisar índices", False)]),
        (1, "Configurar servidor de homologação", "Subir ambiente com Python 3 e PostgreSQL.", "media", "arthur", -1, []),
        (2, "Revisar protótipo das telas", "Validar o fluxo do quadro Kanban com a coordenação.", "media", "ana", 5,
         [("Tela do quadro", True), ("Modal do card", False)]),
        (3, "Criar repositório do projeto", "Repositório Git com README e .gitignore.", "baixa", "bruno", -7, []),
    ],
    ("Projeto 2", 3, ("carla", "arthur", "elisa")): [
        (0, "Inventário de equipamentos", "Listar computadores e impressoras do 3º andar.", "media", "carla", 8, []),
        (0, "Solicitar orçamento de toners", "Pedir 3 orçamentos para o setor de compras.", "alta", "arthur", -2,
         [("Fornecedor A", True), ("Fornecedor B", False), ("Fornecedor C", False)]),
        (1, "Atualizar antivírus das estações", "Aplicar a nova versão em todas as máquinas.", "alta", "elisa", 1, []),
        (2, "Documentar procedimento de backup", "Passo a passo para restauração dos arquivos.", "baixa", "carla", 15, []),
        (3, "Trocar cabos de rede da sala 304", "Cabos danificados substituídos.", "media", "arthur", -4,
         [("Comprar cabos", True), ("Instalar", True)]),
    ],
    ("Projeto 3", 1, ("gabriela", "ana", "carla", "elisa")): [
        (0, "Planejar treinamento dos servidores", "Treinamento sobre o novo sistema de protocolo.", "media", "ana", 20, []),
        (0, "Reservar auditório", "Verificar disponibilidade para a primeira semana do mês.", "baixa", "carla", -5, []),
        (1, "Preparar material de apoio", "Slides e apostila em PDF.", "alta", "carla", 3,
         [("Slides", True), ("Apostila", False), ("Exercícios práticos", False), ("Revisão final", False)]),
        (2, "Validar lista de participantes", "Conferir nomes com o RH.", "media", "elisa", 0, []),
        (3, "Enviar convite por e-mail", "Convite enviado para todos os setores.", "baixa", "gabriela", -10, []),
        (3, "Definir cronograma", "Datas e horários das turmas fechados.", "alta", "ana", -8, []),
    ],
}


class Command(BaseCommand):
    help = "Apaga os projetos e recria projetos, cards e usuários de exemplo (senha 123)."

    @transaction.atomic
    def handle(self, *args, **options):
        andares = {a.numero: a for a in Andar.objects.all()}
        if len(andares) < 5:
            self.stderr.write("Os andares não existem. Rode `manage.py migrate` primeiro.")
            return

        # ---------- Usuários ----------
        usuarios = {}
        for username, (nome, sobrenome, andar, cargo, trocar) in USUARIOS.items():
            u, _ = Usuario.objects.update_or_create(
                username=username,
                defaults={
                    "first_name": nome,
                    "last_name": sobrenome,
                    "email": f"{username}@salvador.ba.gov.br",
                    "andar": andares[andar],
                    "cargo": cargo,
                    "is_active": True,
                    "deve_trocar_senha": trocar,
                },
            )
            u.set_password(SENHA)
            u.save()
            usuarios[username] = u

        # ---------- Projetos ----------
        Quadro.objects.all().delete()
        hoje = date.today()

        for (nome_quadro, andar, membros), cards in QUADROS.items():
            quadro = Quadro.objects.create(nome=nome_quadro, andar=andares[andar])
            quadro.criar_colunas_padrao()
            colunas = list(quadro.colunas.all())
            criador = usuarios[membros[0]]
            for username in membros:
                MembroQuadro.objects.create(quadro=quadro, usuario=usuarios[username], adicionado_por=criador)

            ordem_por_coluna = {}
            for col_idx, titulo, desc, prio, resp, dias, checklist in cards:
                ordem = ordem_por_coluna.get(col_idx, 0)
                ordem_por_coluna[col_idx] = ordem + 1
                card = Card.objects.create(
                    coluna=colunas[col_idx],
                    titulo=titulo,
                    descricao=desc,
                    prioridade=prio,
                    responsavel=usuarios[resp],
                    vencimento=hoje + timedelta(days=dias),
                    ordem=ordem,
                )
                AtividadeCard.objects.create(
                    card=card, usuario=criador, tipo=AtividadeCard.Tipo.CRIADO,
                    descricao=f"criou o card em “{colunas[0].titulo}”",
                )
                AtividadeCard.objects.create(
                    card=card, usuario=criador, tipo=AtividadeCard.Tipo.RESPONSAVEL,
                    descricao=f"definiu {usuarios[resp].nome_exibicao} como responsável",
                )
                for i, (texto, feito) in enumerate(checklist):
                    ChecklistItem.objects.create(card=card, texto=texto, feito=feito, ordem=i)

        # ---------- Um convite pendente de exemplo ----------
        ConviteTransferencia.objects.filter(convidado=usuarios["ana"]).delete()
        ConviteTransferencia.objects.create(
            convidado=usuarios["ana"],
            convidado_por=usuarios["carla"],
            andar_origem=andares[2],
            andar_destino=andares[3],
        )

        self.stdout.write(self.style.SUCCESS(
            f"Pronto: {len(USUARIOS)} usuários (senha \"{SENHA}\"), {len(QUADROS)} projetos e 1 convite pendente."
        ))

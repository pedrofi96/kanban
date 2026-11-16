"""
Ações que ALTERAM o banco no kanban (membros e histórico).
"""

from django.db import transaction
from django.utils import timezone

from .models import AtividadeCard, Card, ChecklistItem, Coluna, MembroQuadro, Quadro

MINIMO_DE_COLUNAS = 3  # contando a "Concluído"


class RegraDeColuna(Exception):
    """A ação quebra uma regra das colunas. A mensagem é mostrada ao usuário."""


def registrar(card, usuario, tipo, descricao):
    AtividadeCard.objects.create(
        card=card,
        usuario=usuario if usuario and usuario.is_authenticated else None,
        tipo=tipo,
        descricao=descricao[:255],
    )


def atualizar_status_do_quadro(quadro):
    """Recalcula e grava se o projeto está concluído: tem pelo menos 1 card e
    todos estão na coluna "Concluído". Chame sempre que um card for criado,
    movido de coluna ou excluído. Só grava no banco quando o status muda."""
    cards = Card.objects.filter(coluna__quadro=quadro)
    concluido = cards.exists() and not cards.filter(coluna__concluida=False).exists()
    if concluido != quadro.concluido:
        quadro.concluido = concluido
        quadro.concluido_em = timezone.now() if concluido else None
        quadro.save(update_fields=["concluido", "concluido_em"])
    return concluido


@transaction.atomic
def criar_quadro(nome, andar, ator):
    quadro = Quadro.objects.create(nome=nome[:120], andar=andar)
    quadro.criar_colunas_padrao()
    # Quem cria entra como membro (o superuser é só de dev, não participa).
    if not ator.is_superuser:
        MembroQuadro.objects.create(quadro=quadro, usuario=ator, adicionado_por=ator)
    return quadro


def adicionar_ao_quadro(quadro, usuario, ator):
    MembroQuadro.objects.get_or_create(
        quadro=quadro, usuario=usuario, defaults={"adicionado_por": ator}
    )


@transaction.atomic
def remover_do_quadro(quadro, usuario, ator, motivo="saiu do projeto"):
    """Tira `usuario` do quadro. Os cards ficam, o responsável fica vazio
    e o histórico registra o que aconteceu."""
    MembroQuadro.objects.filter(quadro=quadro, usuario=usuario).delete()

    cards = list(Card.objects.filter(coluna__quadro=quadro, responsavel=usuario))
    for card in cards:
        registrar(
            card,
            ator,
            AtividadeCard.Tipo.SAIU_DO_PROJETO,
            f"{usuario.nome_exibicao} deixou de ser responsável ({motivo})",
        )
    Card.objects.filter(pk__in=[c.pk for c in cards]).update(responsavel=None)


def remover_de_todos_os_quadros(usuario, ator, motivo):
    for quadro in Quadro.objects.filter(membros=usuario):
        remover_do_quadro(quadro, usuario, ator, motivo)


# ---------- Colunas ----------
# Aqui ficam as regras da coluna em si. QUEM pode mexer é decidido em
# permissoes.pode_gerenciar_colunas, checado na view antes de chamar estas funções.

def _titulo_valido(quadro, titulo, ignorar=None):
    titulo = (titulo or "").strip()[:60]
    if not titulo:
        raise RegraDeColuna("O nome da coluna é obrigatório.")
    repetidas = quadro.colunas.filter(titulo__iexact=titulo)
    if ignorar is not None:
        repetidas = repetidas.exclude(pk=ignorar.pk)
    if repetidas.exists():
        raise RegraDeColuna("Já existe uma coluna com esse nome neste projeto.")
    return titulo


def _renumerar(quadro):
    """Deixa a ordem 0, 1, 2… sem buracos, com a "Concluído" sempre por último."""
    colunas = sorted(quadro.colunas.all(), key=lambda c: (c.concluida, c.ordem, c.pk))
    for ordem, coluna in enumerate(colunas):
        coluna.ordem = ordem
    Coluna.objects.bulk_update(colunas, ["ordem"])

@transaction.atomic
def mover_coluna(coluna, posicao):
    if coluna.concluida:
        raise RegraDeColuna("A coluna “Concluído” não pode ser movida.")
    try:
        posicao = int(posicao)
    except (TypeError, ValueError):
        raise RegraDeColuna("Posição inválida.")

    quadro = coluna.quadro
    outras = list(
        quadro.colunas.filter(concluida=False)
        .exclude(pk=coluna.pk)
        .order_by("ordem","pk")
    )
    posicao = max(0, min(posicao, len(outras)))
    outras.insert(posicao, coluna)

    for ordem, c in enumerate(outras):
        c.ordem = ordem

    Coluna.objects.bulk_update(outras, ["ordem"])
    _renumerar(quadro)

@transaction.atomic
def criar_coluna(quadro, titulo):
    """A coluna nova entra logo antes da "Concluído"."""
    titulo = _titulo_valido(quadro, titulo)
    # ordem alta = depois de todas as comuns; o _renumerar põe a "Concluído" no fim.
    coluna = Coluna.objects.create(quadro=quadro, titulo=titulo, ordem=quadro.colunas.count())
    _renumerar(quadro)
    coluna.refresh_from_db()
    return coluna


def renomear_coluna(coluna, titulo):
    if coluna.concluida:
        raise RegraDeColuna("A coluna “Concluído” não pode ser alterada.")
    coluna.titulo = _titulo_valido(coluna.quadro, titulo, ignorar=coluna)
    coluna.save(update_fields=["titulo"])
    return coluna


@transaction.atomic
def excluir_coluna(coluna):
    quadro = coluna.quadro
    if coluna.concluida:
        raise RegraDeColuna("A coluna “Concluído” não pode ser excluída.")
    if coluna.cards.exists():
        raise RegraDeColuna("Só é possível excluir uma coluna vazia. Mova os cards antes.")
    if quadro.colunas.count() <= MINIMO_DE_COLUNAS:
        raise RegraDeColuna(f"O projeto precisa ter pelo menos {MINIMO_DE_COLUNAS} colunas.")
    coluna.delete()
    _renumerar(quadro)


# ---------- Checklist ----------

def sincronizar_checklist(card, itens):
    """Deixa o checklist do card igual à lista recebida do "Salvar mudanças":
    item com id conhecido é atualizado, item sem id é criado e quem ficou
    de fora da lista é excluído. Levanta ValueError se a lista vier malformada."""
    if not isinstance(itens, list) or not all(isinstance(i, dict) for i in itens):
        raise ValueError("checklist inválido")

    existentes = {item.pk: item for item in card.checklist.all()}
    mantidos = set()
    for ordem, dados in enumerate(itens):
        texto = str(dados.get("texto") or "").strip()[:200]
        if not texto:
            continue
        feito = bool(dados.get("feito"))
        item = existentes.get(dados.get("id"))
        if item is None:
            ChecklistItem.objects.create(card=card, texto=texto, feito=feito, ordem=ordem)
        else:
            item.texto, item.feito, item.ordem = texto, feito, ordem
            item.save()
            mantidos.add(item.pk)
    ChecklistItem.objects.filter(pk__in=set(existentes) - mantidos).delete()

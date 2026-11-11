"""
Ações que ALTERAM o banco no kanban (membros e histórico).
"""

from django.db import transaction

from .models import AtividadeCard, Card, MembroQuadro, Quadro


def registrar(card, usuario, tipo, descricao):
    AtividadeCard.objects.create(
        card=card,
        usuario=usuario if usuario and usuario.is_authenticated else None,
        tipo=tipo,
        descricao=descricao[:255],
    )


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

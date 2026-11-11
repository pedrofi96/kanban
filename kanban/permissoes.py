"""
Regras de permissão dos quadros (projetos) e cards.
"""

from django.db import models

from usuarios.models import Andar
from usuarios.permissoes import _ativo, tem_poder_global

from .models import Quadro


def quadros_visiveis(usuario):
    """QuerySet com os quadros que `usuario` pode ver."""
    if not _ativo(usuario):
        return Quadro.objects.none()
    if tem_poder_global(usuario):
        return Quadro.objects.all()
    if usuario.is_admin_andar:
        # todos do seu andar + os de outros andares em que é membro
        return Quadro.objects.filter(
            models.Q(andar_id=usuario.andar_id) | models.Q(membros=usuario)
        ).distinct()
    return Quadro.objects.filter(membros=usuario)


def e_membro(usuario, quadro):
    return quadro.membros.filter(pk=usuario.pk).exists()


def pode_ver_quadro(usuario, quadro):
    if not _ativo(usuario):
        return False
    if tem_poder_global(usuario):
        return True
    if usuario.is_admin_andar and quadro.andar_id == usuario.andar_id:
        return True
    return e_membro(usuario, quadro)


def pode_mexer_nos_cards(usuario, quadro):
    """Criar, mover, editar e excluir tarefas: todos que veem o quadro."""
    return pode_ver_quadro(usuario, quadro)


def pode_criar_quadro(ator, andar):
    if not _ativo(ator):
        return False
    if tem_poder_global(ator):
        return True
    return ator.is_admin_andar and ator.andar_id == andar.id


def andares_para_criar_quadro(ator):
    """Andares em que `ator` pode criar projetos (para montar o <select>)."""
    if not _ativo(ator):
        return Andar.objects.none()
    if tem_poder_global(ator):
        return Andar.objects.all()
    if ator.is_admin_andar and ator.andar_id:
        return Andar.objects.filter(pk=ator.andar_id)
    return Andar.objects.none()


def pode_administrar_quadro(ator, quadro):
    """Renomear o quadro e gerenciar seus membros."""
    if not _ativo(ator):
        return False
    if tem_poder_global(ator):
        return True
    return ator.is_admin_andar and ator.andar_id == quadro.andar_id


def pode_excluir_quadro(ator, quadro):
    """Excluir o projeto inteiro (com colunas, cards e histórico).
    Mesmas pessoas que administram: admin geral e admin do andar do projeto."""
    return pode_administrar_quadro(ator, quadro)


def pode_adicionar_membro(ator, quadro, alvo):
    """Admin do andar adiciona gente de QUALQUER andar aos quadros do seu andar."""
    return (
        pode_administrar_quadro(ator, quadro)
        and alvo.is_active
        and not alvo.is_superuser
        and not e_membro(alvo, quadro)
    )


def pode_remover_membro(ator, quadro, alvo):
    """Admin tira alguém do quadro, ou o próprio usuário sai sozinho."""
    if not e_membro(alvo, quadro):
        return False
    if _ativo(ator) and ator.pk == alvo.pk:
        return True                       # sair do projeto sozinho
    return pode_administrar_quadro(ator, quadro)

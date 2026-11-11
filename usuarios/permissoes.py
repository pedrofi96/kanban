"""
Regras de permissão de usuários, andares e convites.

Todas as funções respondem True/False e NÃO alteram nada no banco.
Quem faz a ação (a view) chama a função antes e, se for False,
levanta PermissionDenied.
"""

from .models import ConviteTransferencia, Usuario

Cargo = Usuario.Cargo


# ----------------------------------------------------------------------
# Auxiliares
# ----------------------------------------------------------------------

def _ativo(usuario):
    return usuario is not None and usuario.is_authenticated and usuario.is_active


def tem_poder_global(usuario):
    """Superuser (dev) e admin geral enxergam e administram tudo."""
    return _ativo(usuario) and (usuario.is_superuser or usuario.is_admin_geral)


def mesmo_andar(a, b):
    return a.andar_id is not None and a.andar_id == b.andar_id


def e_ultimo_admin_geral_ativo(usuario):
    """True se `usuario` é o único admin geral ativo do sistema."""
    if not (usuario.is_admin_geral and usuario.is_active):
        return False
    outros = Usuario.objects.filter(
        cargo=Cargo.ADMIN_GERAL, is_active=True
    ).exclude(pk=usuario.pk)
    return not outros.exists()


def _admin_andar_alcanca(actor, target):
    """Admin do andar só mexe em usuário/admin do PRÓPRIO andar."""
    return (
            actor.is_admin_andar
            and mesmo_andar(actor, target)
            and not target.is_superuser
            and target.cargo in (Cargo.USUARIO, Cargo.ADMIN_ANDAR)
    )


# ----------------------------------------------------------------------
# Criar / editar
# ----------------------------------------------------------------------

def pode_criar_usuario(actor, andar, cargo):
    """Criar um usuário novo no `andar`, com o `cargo` informado."""
    if not _ativo(actor):
        return False
    if tem_poder_global(actor):
        return True
    return (
            actor.is_admin_andar
            and actor.andar_id == andar.id
            and cargo in (Cargo.USUARIO, Cargo.ADMIN_ANDAR)
    )


def pode_editar_usuario(actor, target):
    """Editar dados cadastrais (nome, e-mail...). Cargo, andar e
    ativação têm funções próprias abaixo."""
    if not _ativo(actor):
        return False
    if actor.is_superuser:
        return True
    if target.is_superuser:
        return False
    if actor.is_admin_geral:
        return True
    return _admin_andar_alcanca(actor, target)


def pode_redefinir_senha(actor, target):
    """Admin define uma senha provisória para outra pessoa.
    A própria senha cada um troca pelo "Meu perfil"."""
    return actor.pk != target.pk and pode_editar_usuario(actor, target)


# ----------------------------------------------------------------------
# Telas de gestão
# ----------------------------------------------------------------------

def pode_ver_usuarios(actor):
    """Acesso à lista de usuários e ao painel de andares."""
    return _ativo(actor) and actor.is_administrador


def usuarios_visiveis(actor):
    """QuerySet dos usuários que `actor` enxerga na lista."""
    if not pode_ver_usuarios(actor):
        return Usuario.objects.none()
    qs = Usuario.objects.select_related("andar")
    if not actor.is_superuser:
        qs = qs.exclude(is_superuser=True)
    if tem_poder_global(actor):
        return qs
    return qs.filter(andar_id=actor.andar_id)


def cargos_que_pode_atribuir(actor):
    """Cargos que aparecem nas telas de criar usuário / alterar cargo."""
    if tem_poder_global(actor):
        return list(Cargo)
    if _ativo(actor) and actor.is_admin_andar:
        return [Cargo.USUARIO, Cargo.ADMIN_ANDAR]
    return []


# ----------------------------------------------------------------------
# Desativar / reativar  (ninguém é excluído)
# ----------------------------------------------------------------------

def pode_alterar_ativacao(actor, target):
    """Desativar ou reativar `alvo`."""
    if not _ativo(actor) or actor.pk == target.pk:
        return False                      # ninguém desativa a si mesmo
    if target.is_superuser:
        return actor.is_superuser
    if e_ultimo_admin_geral_ativo(target):
        return False                      # protege o último admin geral
    if tem_poder_global(actor):
        return True
    return _admin_andar_alcanca(actor, target)


# ----------------------------------------------------------------------
# Promover / rebaixar
# ----------------------------------------------------------------------

def pode_alterar_cargo(actor, target, novo_cargo):
    """Mudar o cargo de `alvo` para `novo_cargo`."""
    if not _ativo(actor) or actor.pk == target.pk:
        return False                      # ninguém promove/rebaixa a si mesmo
    if target.is_superuser or target.cargo == novo_cargo:
        return False
    if e_ultimo_admin_geral_ativo(target):
        return False                      # não pode rebaixar o último
    if tem_poder_global(actor):
        return True
    return (
        _admin_andar_alcanca(actor, target)
        and novo_cargo in (Cargo.USUARIO, Cargo.ADMIN_ANDAR)
    )


# ----------------------------------------------------------------------
# Transferência direta de andar
# ----------------------------------------------------------------------

def pode_transferir(actor, target, andar_destino):
    """Mover `alvo` para `andar_destino` sem convite.

    - Admin geral: move qualquer um (inclusive admins e a si mesmo).
    - Admin do andar: só usuários NORMAIS do próprio andar.
    - Admin do andar sendo movido: só por convite (ver abaixo).
    """
    if not _ativo(actor) or target.is_superuser:
        return False
    if target.andar_id == andar_destino.id:
        return False
    if tem_poder_global(actor):
        return True
    return (
            actor.is_admin_andar
            and actor.pk != target.pk
            and mesmo_andar(actor, target)
            and target.cargo == Cargo.USUARIO
    )


# ----------------------------------------------------------------------
# Convites de transferência (só entre admins do andar)
# ----------------------------------------------------------------------

def _tem_convite_pendente(usuario):
    return ConviteTransferencia.objects.filter(
        convidado=usuario, status=ConviteTransferencia.Status.PENDENTE
    ).exists()


def pode_convidar(actor, convidado) -> bool:
    """Admin do andar X convida admin do andar Y para vir para X."""
    return (
            _ativo(actor)
            and actor.is_admin_andar
            and actor.andar_id is not None
            and convidado.is_active
            and convidado.is_admin_andar
            and convidado.andar_id is not None
            and not mesmo_andar(actor, convidado)
            and not _tem_convite_pendente(convidado)
    )


def pode_ver_convite(actor, convite):
    """Só quem convidou e quem foi convidado (nem o admin geral)."""
    return _ativo(actor) and actor.pk in (convite.convidado_id, convite.convidado_por_id)


def pode_cancelar_convite(actor, convite):
    return (
        _ativo(actor)
        and convite.status == ConviteTransferencia.Status.PENDENTE
        and actor.pk == convite.convidado_por_id
    )


def pode_usar_convites(actor):
    """Tela de convites: só admin do andar (o admin geral transfere direto)."""
    return _ativo(actor) and actor.is_admin_andar and actor.andar_id is not None


def pode_responder_convite(actor, convite):
    """Aceitar ou recusar. Revalida tudo na hora, porque a situação
    pode ter mudado desde que o convite foi criado."""
    if not (
            _ativo(actor)
            and convite.status == ConviteTransferencia.Status.PENDENTE
            and actor.pk == convite.convidado_id
    ):
        return False

    quem_convidou = convite.convidado_por
    return (
            actor.is_admin_andar  # ainda é admin do andar
            and actor.andar_id == convite.andar_origem_id  # ainda está no andar de origem
            and quem_convidou.is_active  # quem convidou ainda está ativo,
            and quem_convidou.is_admin_andar  # ainda é admin do andar
            and quem_convidou.andar_id == convite.andar_destino_id  # e do andar de destino
    )
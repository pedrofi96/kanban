"""
Ações que ALTERAM o banco (usuários, andares e convites).

As views checam a permissão (permissoes.py) e depois chamam estas
funções. Tudo roda em transação: ou faz tudo, ou não faz nada.
"""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import ConviteTransferencia, Usuario
from .signals import usuario_transferido

Cargo = Usuario.Cargo
Status = ConviteTransferencia.Status


def criar_usuario(form):
    """Salva o usuário do formulário com a senha provisória."""
    usuario = form.save(commit=False)
    usuario.set_password(form.cleaned_data["senha_provisoria"])
    usuario.deve_trocar_senha = True
    usuario.save()
    return usuario


def redefinir_senha(usuario, senha_provisoria):
    usuario.set_password(senha_provisoria)
    usuario.deve_trocar_senha = True
    usuario.save(update_fields=["password", "deve_trocar_senha"])


def alterar_ativacao(usuario, ativo):
    usuario.is_active = ativo
    usuario.save(update_fields=["is_active"])


def alterar_cargo(usuario, novo_cargo):
    usuario.cargo = novo_cargo
    usuario.save(update_fields=["cargo"])


@transaction.atomic
def transferir_usuario(usuario, andar_destino, ator):
    """Muda o andar de `usuario`.

    - Sai de TODOS os projetos (o kanban faz isso ao receber o sinal).
    - Admin do andar transferido vira usuário normal no novo andar.
    - Convites pendentes envolvendo a pessoa são cancelados.
    """
    andar_origem = usuario.andar
    usuario.andar = andar_destino
    if usuario.is_admin_andar:
        usuario.cargo = Cargo.USUARIO
    usuario.save(update_fields=["andar", "cargo"])

    ConviteTransferencia.objects.filter(status=Status.PENDENTE).filter(
        Q(convidado=usuario) | Q(convidado_por=usuario)
    ).update(status=Status.CANCELADO, respondido_em=timezone.now())

    usuario_transferido.send(
        sender=Usuario, usuario=usuario, andar_origem=andar_origem, ator=ator
    )


# ----------------------------------------------------------------------
# Convites
# ----------------------------------------------------------------------

def convidar(ator, convidado):
    return ConviteTransferencia.objects.create(
        convidado=convidado,
        convidado_por=ator,
        andar_origem=convidado.andar,
        andar_destino=ator.andar,
    )


def _responder(convite, status):
    convite.status = status
    convite.respondido_em = timezone.now()
    convite.save(update_fields=["status", "respondido_em"])


@transaction.atomic
def aceitar_convite(convite):
    convidado = convite.convidado
    transferir_usuario(convidado, convite.andar_destino, ator=convidado)
    # transferir_usuario cancela os pendentes; este aqui fica como aceito.
    _responder(convite, Status.ACEITO)


def recusar_convite(convite):
    _responder(convite, Status.RECUSADO)


def cancelar_convite(convite):
    _responder(convite, Status.CANCELADO)

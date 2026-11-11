from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import permissoes, services
from .forms import (
    AlterarCargoForm,
    ConvidarForm,
    CriarUsuarioForm,
    EditarUsuarioForm,
    PerfilForm,
    RedefinirSenhaForm,
    TransferirForm,
    TrocarSenhaForm,
)
from .models import Andar, ConviteTransferencia, Usuario

Cargo = Usuario.Cargo


def _exigir(condicao):
    if not condicao:
        raise PermissionDenied


# ----------------------------------------------------------------------
# Minha conta
# ----------------------------------------------------------------------

@login_required
def trocar_senha(request):
    obrigatoria = request.user.deve_trocar_senha
    form = TrocarSenhaForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        usuario.deve_trocar_senha = False
        usuario.save(update_fields=["deve_trocar_senha"])
        update_session_auth_hash(request, usuario)  # não desloga depois de trocar
        messages.success(request, "Senha alterada com sucesso.")
        return redirect("index" if obrigatoria else "perfil")
    return render(request, "usuarios/trocar_senha.html", {"form": form, "obrigatoria": obrigatoria})


@login_required
def perfil(request):
    form = PerfilForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Seus dados foram atualizados.")
        return redirect("perfil")
    return render(request, "usuarios/perfil.html", {"form": form})


# ----------------------------------------------------------------------
# Usuários
# ----------------------------------------------------------------------

@login_required
def lista_usuarios(request):
    _exigir(permissoes.pode_ver_usuarios(request.user))
    usuarios = permissoes.usuarios_visiveis(request.user)

    filtros = {
        "q": request.GET.get("q", "").strip(),
        "andar": request.GET.get("andar", ""),
        "cargo": request.GET.get("cargo", ""),
        "status": request.GET.get("status", "ativos"),
    }
    if filtros["q"]:
        q = filtros["q"]
        usuarios = usuarios.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q)
            | Q(username__icontains=q) | Q(email__icontains=q)
        )
    if filtros["andar"]:
        usuarios = usuarios.filter(andar_id=filtros["andar"])
    if filtros["cargo"]:
        usuarios = usuarios.filter(cargo=filtros["cargo"])
    if filtros["status"] == "ativos":
        usuarios = usuarios.filter(is_active=True)
    elif filtros["status"] == "inativos":
        usuarios = usuarios.filter(is_active=False)

    return render(request, "usuarios/lista.html", {
        "usuarios": usuarios.order_by("andar__numero", "first_name", "last_name"),
        "filtros": filtros,
        "andares": Andar.objects.all() if permissoes.tem_poder_global(request.user) else None,
        "cargos": Cargo.choices,
    })


@login_required
def criar_usuario(request):
    _exigir(permissoes.pode_ver_usuarios(request.user))
    form = CriarUsuarioForm(request.POST or None, ator=request.user)
    if request.method == "POST" and form.is_valid():
        usuario = services.criar_usuario(form)
        messages.success(request, f"Usuário {usuario.nome_exibicao} criado. Ele vai trocar a senha no primeiro acesso.")
        return redirect("usuario_detalhe", usuario.pk)
    return render(request, "usuarios/criar.html", {"form": form})


def _contexto_detalhe(request, alvo, **forms):
    ator = request.user
    pode_cargo = any(permissoes.pode_alterar_cargo(ator, alvo, c) for c in Cargo)
    pode_transferir = any(
        permissoes.pode_transferir(ator, alvo, a) for a in Andar.objects.exclude(pk=alvo.andar_id)
    )
    contexto = {
        "alvo": alvo,
        "e_voce": ator.pk == alvo.pk,
        "pode_editar": permissoes.pode_editar_usuario(ator, alvo),
        "pode_senha": permissoes.pode_redefinir_senha(ator, alvo),
        "pode_ativacao": permissoes.pode_alterar_ativacao(ator, alvo),
        "pode_cargo": pode_cargo,
        "pode_transferir": pode_transferir,
        "so_por_convite": alvo.is_admin_andar and not permissoes.tem_poder_global(ator),
        "form_dados": EditarUsuarioForm(instance=alvo),
        "form_senha": RedefinirSenhaForm(),
        "form_cargo": AlterarCargoForm(ator=ator, alvo=alvo),
        "form_transferir": TransferirForm(alvo=alvo),
        "projetos": alvo.participacoes.select_related("quadro__andar").order_by("quadro__nome"),
    }
    contexto.update(forms)
    return contexto


def _alvo(request, usuario_id):
    """Busca o usuário e garante que quem pede pode vê-lo."""
    alvo = get_object_or_404(Usuario.objects.select_related("andar"), pk=usuario_id)
    _exigir(permissoes.usuarios_visiveis(request.user).filter(pk=alvo.pk).exists())
    return alvo


@login_required
def usuario_detalhe(request, usuario_id):
    alvo = _alvo(request, usuario_id)
    if request.method == "POST":
        _exigir(permissoes.pode_editar_usuario(request.user, alvo))
        form = EditarUsuarioForm(request.POST, instance=alvo)
        if form.is_valid():
            form.save()
            messages.success(request, "Dados atualizados.")
            return redirect("usuario_detalhe", alvo.pk)
        alvo.refresh_from_db()
        return render(request, "usuarios/detalhe.html", _contexto_detalhe(request, alvo, form_dados=form))
    return render(request, "usuarios/detalhe.html", _contexto_detalhe(request, alvo))


@login_required
@require_POST
def usuario_senha(request, usuario_id):
    alvo = _alvo(request, usuario_id)
    _exigir(permissoes.pode_redefinir_senha(request.user, alvo))
    form = RedefinirSenhaForm(request.POST)
    if form.is_valid():
        services.redefinir_senha(alvo, form.cleaned_data["senha_provisoria"])
        messages.success(request, f"Senha provisória definida. {alvo.nome_exibicao} vai trocá-la no próximo acesso.")
        return redirect("usuario_detalhe", alvo.pk)
    return render(request, "usuarios/detalhe.html", _contexto_detalhe(request, alvo, form_senha=form))


@login_required
@require_POST
def usuario_ativacao(request, usuario_id):
    alvo = _alvo(request, usuario_id)
    _exigir(permissoes.pode_alterar_ativacao(request.user, alvo))
    services.alterar_ativacao(alvo, not alvo.is_active)
    messages.success(request, f"{alvo.nome_exibicao} foi {'reativado' if alvo.is_active else 'desativado'}.")
    return redirect("usuario_detalhe", alvo.pk)


@login_required
@require_POST
def usuario_cargo(request, usuario_id):
    alvo = _alvo(request, usuario_id)
    form = AlterarCargoForm(request.POST, ator=request.user, alvo=alvo)
    if form.is_valid():
        novo = form.cleaned_data["cargo"]
        if novo == alvo.cargo:
            return redirect("usuario_detalhe", alvo.pk)
        _exigir(permissoes.pode_alterar_cargo(request.user, alvo, novo))
        services.alterar_cargo(alvo, novo)
        messages.success(request, f"{alvo.nome_exibicao} agora é {alvo.get_cargo_display()}.")
    return redirect("usuario_detalhe", alvo.pk)


@login_required
@require_POST
def usuario_transferir(request, usuario_id):
    alvo = _alvo(request, usuario_id)
    form = TransferirForm(request.POST, alvo=alvo)
    if form.is_valid():
        andar = form.cleaned_data["andar"]
        _exigir(permissoes.pode_transferir(request.user, alvo, andar))
        services.transferir_usuario(alvo, andar, ator=request.user)
        messages.success(request, f"{alvo.nome_exibicao} foi transferido para o {andar} e saiu de todos os projetos.")
        # Admin do andar deixa de enxergar quem saiu do seu andar.
        if permissoes.usuarios_visiveis(request.user).filter(pk=alvo.pk).exists():
            return redirect("usuario_detalhe", alvo.pk)
        return redirect("usuarios_lista")
    return redirect("usuario_detalhe", alvo.pk)


# ----------------------------------------------------------------------
# Andares
# ----------------------------------------------------------------------

@login_required
def painel_andares(request):
    _exigir(permissoes.pode_ver_usuarios(request.user))
    andares = Andar.objects.annotate(
        total=Count("usuarios", filter=Q(usuarios__is_active=True, usuarios__is_superuser=False), distinct=True),
        projetos=Count("quadros", distinct=True),
    )
    admins = (
        Usuario.objects.filter(cargo=Cargo.ADMIN_ANDAR, is_active=True)
        .order_by("first_name")
    )
    por_andar = {}
    for admin in admins:
        por_andar.setdefault(admin.andar_id, []).append(admin)
    linhas = [{"andar": a, "admins": por_andar.get(a.id, [])} for a in andares]
    return render(request, "usuarios/andares.html", {"linhas": linhas})


# ----------------------------------------------------------------------
# Convites de transferência
# ----------------------------------------------------------------------

@login_required
def convites(request):
    _exigir(permissoes.pode_usar_convites(request.user))
    form = ConvidarForm(request.POST or None, ator=request.user)
    if request.method == "POST" and form.is_valid():
        convite = services.convidar(request.user, form.cleaned_data["convidado"])
        messages.success(request, f"Convite enviado para {convite.convidado.nome_exibicao}.")
        return redirect("convites")

    base = ConviteTransferencia.objects.select_related(
        "convidado", "convidado_por", "andar_origem", "andar_destino"
    )
    return render(request, "usuarios/convites.html", {
        "form": form,
        "recebidos": base.filter(convidado=request.user),
        "enviados": base.filter(convidado_por=request.user),
    })


@login_required
@require_POST
def responder_convite(request, convite_id, acao):
    convite = get_object_or_404(ConviteTransferencia, pk=convite_id)
    _exigir(permissoes.pode_ver_convite(request.user, convite))

    if acao == "cancelar":
        _exigir(permissoes.pode_cancelar_convite(request.user, convite))
        services.cancelar_convite(convite)
        messages.success(request, "Convite cancelado.")
    elif acao in ("aceitar", "recusar"):
        if not permissoes.pode_responder_convite(request.user, convite):
            messages.error(request, "Este convite não é mais válido (alguém mudou de cargo ou de andar).")
            return redirect("convites")
        if acao == "aceitar":
            services.aceitar_convite(convite)
            messages.success(
                request,
                f"Você agora faz parte do {convite.andar_destino} como usuário. "
                "Um administrador de lá pode te promover.",
            )
            return redirect("index")
        services.recusar_convite(convite)
        messages.success(request, "Convite recusado.")
    else:
        raise PermissionDenied
    return redirect("convites")

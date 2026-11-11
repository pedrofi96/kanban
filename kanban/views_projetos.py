"""
Telas de gestão dos projetos (quadros): lista, criação, renomear e membros.
"""

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from usuarios.forms import EstiloMixin

from . import permissoes, services
from .models import Quadro

Usuario = get_user_model()


def _exigir(condicao):
    if not condicao:
        raise PermissionDenied


class NovoProjetoForm(EstiloMixin, forms.Form):
    nome = forms.CharField(label="Nome do projeto", max_length=120)
    andar = forms.ModelChoiceField(label="Andar", queryset=None, empty_label=None)

    def __init__(self, *args, ator, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["andar"].queryset = permissoes.andares_para_criar_quadro(ator)
        if ator.andar_id:
            self.fields["andar"].initial = ator.andar_id


class RenomearForm(EstiloMixin, forms.Form):
    nome = forms.CharField(label="Nome", max_length=120)


class AdicionarMembroForm(EstiloMixin, forms.Form):
    usuario = forms.ModelChoiceField(label="Pessoa", queryset=None, empty_label="Selecione…")

    def __init__(self, *args, quadro, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["usuario"].queryset = (
            Usuario.objects.filter(is_active=True, is_superuser=False)
            .exclude(pk__in=quadro.membros.values("pk"))
            .select_related("andar")
            .order_by("andar__numero", "first_name")
        )
        self.fields["usuario"].label_from_instance = (
            lambda u: f"{u.nome_exibicao} — {u.andar or 'sem andar'}"
        )


@login_required
def lista_projetos(request):
    quadros = (
        permissoes.quadros_visiveis(request.user)
        .select_related("andar")
        .annotate(
            total_membros=Count("membros", distinct=True),
            total_cards=Count("colunas__cards", distinct=True),
        )
        .order_by("andar__numero", "nome")
    )
    form = NovoProjetoForm(request.POST or None, ator=request.user)
    pode_criar = form.fields["andar"].queryset.exists()

    if request.method == "POST":
        _exigir(pode_criar)
        if form.is_valid():
            andar = form.cleaned_data["andar"]
            _exigir(permissoes.pode_criar_quadro(request.user, andar))
            quadro = services.criar_quadro(form.cleaned_data["nome"], andar, request.user)
            messages.success(request, f"Projeto “{quadro.nome}” criado. Adicione os membros abaixo.")
            return redirect("projeto_detalhe", quadro.pk)

    linhas = [
        {
            "quadro": q,
            "pode_administrar": permissoes.pode_administrar_quadro(request.user, q),
            "pode_excluir": permissoes.pode_excluir_quadro(request.user, q),
        }
        for q in quadros
    ]
    return render(request, "kanban/projetos.html", {"linhas": linhas, "form": form, "pode_criar": pode_criar})


@login_required
def projeto_detalhe(request, quadro_id):
    quadro = get_object_or_404(Quadro.objects.select_related("andar"), pk=quadro_id)
    _exigir(permissoes.pode_ver_quadro(request.user, quadro))
    pode_administrar = permissoes.pode_administrar_quadro(request.user, quadro)

    participacoes = quadro.participacoes.select_related("usuario__andar", "adicionado_por").order_by(
        "usuario__first_name"
    )
    membros = [
        {
            "p": p,
            "pode_remover": permissoes.pode_remover_membro(request.user, quadro, p.usuario),
        }
        for p in participacoes
    ]
    return render(request, "kanban/projeto_detalhe.html", {
        "quadro": quadro,
        "membros": membros,
        "pode_administrar": pode_administrar,
        "e_membro": permissoes.e_membro(request.user, quadro),
        "form_renomear": RenomearForm(initial={"nome": quadro.nome}),
        "form_membro": AdicionarMembroForm(quadro=quadro),
    })


@login_required
@require_POST
def projeto_renomear(request, quadro_id):
    quadro = get_object_or_404(Quadro, pk=quadro_id)
    _exigir(permissoes.pode_administrar_quadro(request.user, quadro))
    form = RenomearForm(request.POST)
    if form.is_valid():
        quadro.nome = form.cleaned_data["nome"]
        quadro.save(update_fields=["nome"])
        messages.success(request, "Projeto renomeado.")
    return redirect("projeto_detalhe", quadro.pk)


@login_required
@require_POST
def projeto_excluir(request, quadro_id):
    quadro = get_object_or_404(Quadro, pk=quadro_id)
    _exigir(permissoes.pode_excluir_quadro(request.user, quadro))
    nome = quadro.nome
    quadro.delete()  # apaga junto colunas, cards, checklist, histórico e membros (CASCADE)
    messages.success(request, f"Projeto “{nome}” excluído.")
    return redirect("projetos")


@login_required
@require_POST
def projeto_adicionar_membro(request, quadro_id):
    quadro = get_object_or_404(Quadro, pk=quadro_id)
    _exigir(permissoes.pode_administrar_quadro(request.user, quadro))
    form = AdicionarMembroForm(request.POST, quadro=quadro)
    if form.is_valid():
        alvo = form.cleaned_data["usuario"]
        _exigir(permissoes.pode_adicionar_membro(request.user, quadro, alvo))
        services.adicionar_ao_quadro(quadro, alvo, request.user)
        messages.success(request, f"{alvo.nome_exibicao} agora participa do projeto.")
    else:
        messages.error(request, "Escolha uma pessoa válida.")
    return redirect("projeto_detalhe", quadro.pk)


@login_required
@require_POST
def projeto_remover_membro(request, quadro_id, usuario_id):
    quadro = get_object_or_404(Quadro, pk=quadro_id)
    alvo = get_object_or_404(Usuario, pk=usuario_id)
    _exigir(permissoes.pode_remover_membro(request.user, quadro, alvo))

    saindo = alvo.pk == request.user.pk
    services.remover_do_quadro(
        quadro, alvo, request.user,
        motivo="saiu do projeto" if saindo else f"removido por {request.user.nome_exibicao}",
    )
    if saindo:
        messages.success(request, f"Você saiu do projeto “{quadro.nome}”.")
        if not permissoes.pode_ver_quadro(request.user, quadro):
            return redirect("projetos")
    else:
        messages.success(request, f"{alvo.nome_exibicao} foi removido do projeto.")
    return redirect("projeto_detalhe", quadro.pk)

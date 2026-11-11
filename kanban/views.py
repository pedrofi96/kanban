"""
Página do quadro + API JSON usada pelo Alpine (app.js).

Toda rota da API exige login (401) e checa a permissão no quadro (403).
"""

import json
from datetime import date
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from usuarios.models import Andar, Usuario

from . import permissoes, services
from .models import AtividadeCard, Card, ChecklistItem, Coluna, Quadro


# ---------- Auxiliares ----------

def api_login_required(view):
    """Como o @login_required, mas responde JSON 401 em vez de redirecionar."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"erro": "Sua sessão expirou. Entre novamente."}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


def _negado():
    return JsonResponse({"erro": "Você não tem permissão para isso."}, status=403)


def _corpo(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}


def _quadro_dict(quadro, usuario):
    dados = quadro.to_dict()
    dados["pode_administrar"] = permissoes.pode_administrar_quadro(usuario, quadro)
    dados["e_membro"] = any(m["id"] == usuario.pk for m in dados["membros"])
    return dados


def _estado(usuario):
    """Estado enviado ao front: só os quadros que o usuário pode ver."""
    quadros = (
        permissoes.quadros_visiveis(usuario)
        .select_related("andar")
        .prefetch_related("colunas")
    )
    return {
        "eu": usuario.to_dict(),
        "andares": [
            {"id": a.id, "nome": str(a)}
            for a in permissoes.andares_para_criar_quadro(usuario)
        ],
        "quadros": [_quadro_dict(q, usuario) for q in quadros],
    }


# ---------- Página ----------

@login_required
@ensure_csrf_cookie
def index(request):
    return render(request, "kanban/index.html", {"estado": _estado(request.user)})


@api_login_required
@require_http_methods(["GET"])
def estado(request):
    return JsonResponse(_estado(request.user))


# ---------- Quadros ----------

@api_login_required
@require_http_methods(["POST"])
def criar_quadro(request):
    dados = _corpo(request)
    nome = (dados.get("nome") or "").strip() or "Novo quadro"
    andar_id = dados.get("andar_id") or request.user.andar_id
    andar = Andar.objects.filter(pk=andar_id).first()
    if andar is None or not permissoes.pode_criar_quadro(request.user, andar):
        return _negado()
    quadro = services.criar_quadro(nome, andar, request.user)
    return JsonResponse(_quadro_dict(quadro, request.user), status=201)


@api_login_required
@require_http_methods(["POST"])
def sair_do_quadro(request, quadro_id):
    quadro = get_object_or_404(Quadro, pk=quadro_id)
    if not permissoes.pode_remover_membro(request.user, quadro, request.user):
        return _negado()
    services.remover_do_quadro(quadro, request.user, request.user, motivo="saiu do projeto")
    return JsonResponse({"ok": True, "ainda_ve": permissoes.pode_ver_quadro(request.user, quadro)})


@api_login_required
@require_http_methods(["GET", "POST"])
def membros_do_quadro(request, quadro_id):
    """GET: pessoas que podem ser adicionadas. POST {usuario_id}: adiciona ao quadro."""
    quadro = get_object_or_404(Quadro, pk=quadro_id)
    if not permissoes.pode_administrar_quadro(request.user, quadro):
        return _negado()

    if request.method == "GET":
        candidatos = (
            Usuario.objects.filter(is_active=True, is_superuser=False)
            .exclude(pk__in=quadro.membros.values("pk"))
            .select_related("andar")
            .order_by("andar__numero", "first_name", "last_name")
        )
        return JsonResponse({"candidatos": [u.to_dict() for u in candidatos]})

    alvo = Usuario.objects.filter(pk=_corpo(request).get("usuario_id")).first()
    if alvo is None or not permissoes.pode_adicionar_membro(request.user, quadro, alvo):
        return JsonResponse({"erro": "Não foi possível adicionar essa pessoa."}, status=400)
    services.adicionar_ao_quadro(quadro, alvo, request.user)
    return JsonResponse(_quadro_dict(quadro, request.user))


# ---------- Cards ----------

@api_login_required
@require_http_methods(["POST"])
def criar_card(request):
    dados = _corpo(request)
    coluna = get_object_or_404(Coluna.objects.select_related("quadro"), pk=dados.get("coluna_id"))
    if not permissoes.pode_mexer_nos_cards(request.user, coluna.quadro):
        return _negado()
    titulo = (dados.get("titulo") or "").strip()
    if not titulo:
        return JsonResponse({"erro": "Título é obrigatório."}, status=400)
    proxima = (coluna.cards.aggregate(m=Max("ordem"))["m"] or -1) + 1
    card = Card.objects.create(
        coluna=coluna,
        titulo=titulo[:200],
        prioridade=dados.get("prioridade") or Card.Prioridade.MEDIA,
        ordem=proxima,
    )
    services.registrar(card, request.user, AtividadeCard.Tipo.CRIADO, f"criou o card em “{coluna.titulo}”")
    return JsonResponse(card.to_dict(), status=201)


CAMPOS_EDITAVEIS = {"titulo", "descricao", "prioridade", "vencimento", "responsavel_id"}


@api_login_required
@require_http_methods(["PATCH", "DELETE"])
def card_detalhe(request, card_id):
    card = get_object_or_404(Card.objects.select_related("coluna__quadro", "responsavel"), pk=card_id)
    quadro = card.coluna.quadro
    if not permissoes.pode_mexer_nos_cards(request.user, quadro):
        return _negado()

    if request.method == "DELETE":
        card.delete()
        return JsonResponse({"ok": True})

    dados = {k: v for k, v in _corpo(request).items() if k in CAMPOS_EDITAVEIS}
    if "prioridade" in dados and dados["prioridade"] not in Card.Prioridade.values:
        return JsonResponse({"erro": "Prioridade inválida."}, status=400)
    if "vencimento" in dados:
        dados["vencimento"] = date.fromisoformat(dados["vencimento"]) if dados["vencimento"] else None
    if "titulo" in dados and not dados["titulo"].strip():
        return JsonResponse({"erro": "Título é obrigatório."}, status=400)

    novo_responsavel = None
    if "responsavel_id" in dados and dados["responsavel_id"] is not None:
        novo_responsavel = quadro.membros.filter(pk=dados["responsavel_id"]).first()
        if novo_responsavel is None:
            return JsonResponse({"erro": "O responsável precisa ser membro do projeto."}, status=400)

    if "responsavel_id" in dados and dados["responsavel_id"] != card.responsavel_id:
        descricao = (
            f"definiu {novo_responsavel.nome_exibicao} como responsável"
            if novo_responsavel else "removeu o responsável"
        )
        services.registrar(card, request.user, AtividadeCard.Tipo.RESPONSAVEL, descricao)

    for campo, valor in dados.items():
        setattr(card, campo, valor)
    card.save()
    return JsonResponse(card.to_dict())


@api_login_required
@require_http_methods(["GET"])
def atividades_do_card(request, card_id):
    card = get_object_or_404(Card.objects.select_related("coluna__quadro"), pk=card_id)
    if not permissoes.pode_ver_quadro(request.user, card.coluna.quadro):
        return _negado()
    atividades = card.atividades.select_related("usuario")[:50]
    return JsonResponse({"atividades": [a.to_dict() for a in atividades]})


@api_login_required
@require_http_methods(["POST"])
def mover_card(request, card_id):
    """Move o card para `coluna_id` na posição `ordem` e renumera as colunas afetadas."""
    dados = _corpo(request)
    card = get_object_or_404(Card.objects.select_related("coluna__quadro"), pk=card_id)
    if not permissoes.pode_mexer_nos_cards(request.user, card.coluna.quadro):
        return _negado()
    destino = get_object_or_404(Coluna, pk=dados.get("coluna_id"), quadro=card.coluna.quadro)
    posicao = max(0, int(dados.get("ordem", 0)))

    with transaction.atomic():
        origem = card.coluna
        irmaos = list(destino.cards.exclude(pk=card.pk).order_by("ordem"))
        irmaos.insert(min(posicao, len(irmaos)), card)
        card.coluna = destino
        for i, c in enumerate(irmaos):
            c.ordem = i
        Card.objects.bulk_update(irmaos, ["ordem", "coluna"])

        if origem.pk != destino.pk:
            restantes = list(origem.cards.order_by("ordem"))
            for i, c in enumerate(restantes):
                c.ordem = i
            Card.objects.bulk_update(restantes, ["ordem"])
            services.registrar(
                card, request.user, AtividadeCard.Tipo.MOVIDO,
                f"moveu de “{origem.titulo}” para “{destino.titulo}”",
            )

    return JsonResponse({"ok": True})


# ---------- Checklist ----------

@api_login_required
@require_http_methods(["POST"])
def criar_item(request, card_id):
    card = get_object_or_404(Card.objects.select_related("coluna__quadro"), pk=card_id)
    if not permissoes.pode_mexer_nos_cards(request.user, card.coluna.quadro):
        return _negado()
    texto = (_corpo(request).get("texto") or "").strip()
    if not texto:
        return JsonResponse({"erro": "Texto é obrigatório."}, status=400)
    proxima = (card.checklist.aggregate(m=Max("ordem"))["m"] or -1) + 1
    item = ChecklistItem.objects.create(card=card, texto=texto[:200], ordem=proxima)
    return JsonResponse(item.to_dict(), status=201)


@api_login_required
@require_http_methods(["PATCH", "DELETE"])
def item_detalhe(request, item_id):
    item = get_object_or_404(ChecklistItem.objects.select_related("card__coluna__quadro"), pk=item_id)
    if not permissoes.pode_mexer_nos_cards(request.user, item.card.coluna.quadro):
        return _negado()
    if request.method == "DELETE":
        item.delete()
        return JsonResponse({"ok": True})
    dados = _corpo(request)
    if "feito" in dados:
        item.feito = bool(dados["feito"])
    if "texto" in dados and dados["texto"].strip():
        item.texto = dados["texto"].strip()[:200]
    item.save()
    return JsonResponse(item.to_dict())

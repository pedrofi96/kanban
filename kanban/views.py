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


def _data(texto):
    """Converte "2026-11-30" em date. Vazio vira None; formato errado levanta ValueError."""
    return date.fromisoformat(texto) if texto else None


def _quadro_dict(quadro, usuario):
    dados = quadro.to_dict()
    dados["pode_administrar"] = permissoes.pode_administrar_quadro(usuario, quadro)
    # O front usa estas flags para esconder/travar botões (a regra de verdade é checada nas views).
    dados["pode_excluir_card"] = permissoes.pode_excluir_card(usuario, quadro)
    dados["pode_alterar_vencimento"] = permissoes.pode_alterar_vencimento(usuario, quadro)
    dados["pode_gerenciar_colunas"] = permissoes.pode_gerenciar_colunas(usuario, quadro)
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


# ---------- Colunas ----------

def _colunas(quadro):
    """As três rotas de coluna devolvem a lista inteira: o front só troca a lista do quadro."""
    return JsonResponse({"colunas": [c.to_dict() for c in quadro.colunas.all()]})


@api_login_required
@require_http_methods(["POST"])
def criar_coluna(request, quadro_id):
    quadro = get_object_or_404(Quadro, pk=quadro_id)
    if not permissoes.pode_gerenciar_colunas(request.user, quadro):
        return _negado()
    try:
        services.criar_coluna(quadro, _corpo(request).get("titulo"))
    except services.RegraDeColuna as erro:
        return JsonResponse({"erro": str(erro)}, status=400)
    return _colunas(quadro)


@api_login_required
@require_http_methods(["PATCH", "DELETE"])
def coluna_detalhe(request, coluna_id):
    coluna = get_object_or_404(Coluna.objects.select_related("quadro"), pk=coluna_id)
    quadro = coluna.quadro
    if not permissoes.pode_gerenciar_colunas(request.user, quadro):
        return _negado()
    try:
        if request.method == "DELETE":
            services.excluir_coluna(coluna)
        else:
            services.renomear_coluna(coluna, _corpo(request).get("titulo"))
    except services.RegraDeColuna as erro:
        return JsonResponse({"erro": str(erro)}, status=400)
    return _colunas(quadro)

@api_login_required
@require_http_methods(["POST"])
def mover_coluna(request, coluna_id):
    """Move a coluna para a posição `ordem` (0 = primeira). Devolve a lista de colunas."""
    coluna = get_object_or_404(Coluna.objects.select_related("quadro"), pk=coluna_id)
    quadro = coluna.quadro
    if not permissoes.pode_gerenciar_colunas(request.user, quadro):
        return _negado()
    try:
        services.mover_coluna(coluna, _corpo(request).get("ordem"))
    except services.RegraDeColuna as erro:
        return JsonResponse({"erro": str(erro)}, status=400)
    return _colunas(quadro)

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
    # Na criação, qualquer um que vê o quadro pode definir a data de vencimento.
    try:
        vencimento = _data(dados.get("vencimento"))
    except (TypeError, ValueError):
        return JsonResponse({"erro": "Data de vencimento inválida."}, status=400)
    proxima = (coluna.cards.aggregate(m=Max("ordem"))["m"] or -1) + 1
    card = Card.objects.create(
        coluna=coluna,
        titulo=titulo[:200],
        prioridade=dados.get("prioridade") or Card.Prioridade.MEDIA,
        vencimento=vencimento,
        ordem=proxima,
    )
    services.registrar(card, request.user, AtividadeCard.Tipo.CRIADO, f"criou o card em “{coluna.titulo}”")
    services.atualizar_status_do_quadro(coluna.quadro)
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
        if not permissoes.pode_excluir_card(request.user, quadro):
            return JsonResponse({"erro": "Só o administrador do andar pode excluir cards."}, status=403)
        card.delete()
        services.atualizar_status_do_quadro(quadro)
        return JsonResponse({"ok": True})

    corpo = _corpo(request)
    dados = {k: v for k, v in corpo.items() if k in CAMPOS_EDITAVEIS}
    if "prioridade" in dados and dados["prioridade"] not in Card.Prioridade.values:
        return JsonResponse({"erro": "Prioridade inválida."}, status=400)
    if "vencimento" in dados:
        try:
            dados["vencimento"] = _data(dados["vencimento"])
        except (TypeError, ValueError):
            return JsonResponse({"erro": "Data de vencimento inválida."}, status=400)
        # Só barra se a data MUDOU: assim o front pode reenviar a mesma data sem erro.
        mudou = dados["vencimento"] != card.vencimento
        if mudou and not permissoes.pode_alterar_vencimento(request.user, quadro):
            return JsonResponse(
                {"erro": "Só o administrador do andar pode alterar a data de vencimento."}, status=403
            )
    if "titulo" in dados and not dados["titulo"].strip():
        return JsonResponse({"erro": "Título é obrigatório."}, status=400)

    novo_responsavel = None
    if "responsavel_id" in dados and dados["responsavel_id"] is not None:
        novo_responsavel = quadro.membros.filter(pk=dados["responsavel_id"]).first()
        if novo_responsavel is None:
            return JsonResponse({"erro": "O responsável precisa ser membro do projeto."}, status=400)

    # O "Salvar mudanças" manda campos e checklist juntos: ou grava tudo, ou não grava nada.
    try:
        with transaction.atomic():
            if "checklist" in corpo:
                services.sincronizar_checklist(card, corpo["checklist"])

            if "responsavel_id" in dados and dados["responsavel_id"] != card.responsavel_id:
                descricao = (
                    f"definiu {novo_responsavel.nome_exibicao} como responsável"
                    if novo_responsavel else "removeu o responsável"
                )
                services.registrar(card, request.user, AtividadeCard.Tipo.RESPONSAVEL, descricao)

            for campo, valor in dados.items():
                setattr(card, campo, valor)
            card.save()
    except ValueError:
        return JsonResponse({"erro": "Checklist inválido."}, status=400)
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
            services.atualizar_status_do_quadro(origem.quadro)

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

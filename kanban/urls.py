from django.urls import path

from . import views, views_projetos

urlpatterns = [
    path("", views.index, name="index"),

    # Gestão de projetos
    path("projetos/", views_projetos.lista_projetos, name="projetos"),
    path("projetos/<int:quadro_id>/", views_projetos.projeto_detalhe, name="projeto_detalhe"),
    path("projetos/<int:quadro_id>/renomear/", views_projetos.projeto_renomear, name="projeto_renomear"),
    path("projetos/<int:quadro_id>/excluir/", views_projetos.projeto_excluir, name="projeto_excluir"),
    path("projetos/<int:quadro_id>/membros/", views_projetos.projeto_adicionar_membro, name="projeto_adicionar_membro"),
    path(
        "projetos/<int:quadro_id>/membros/<int:usuario_id>/remover/",
        views_projetos.projeto_remover_membro,
        name="projeto_remover_membro",
    ),

    # API do quadro (Alpine)
    path("api/estado/", views.estado),
    path("api/quadros/", views.criar_quadro),
    path("api/quadros/<int:quadro_id>/sair/", views.sair_do_quadro),
    path("api/quadros/<int:quadro_id>/membros/", views.membros_do_quadro),
    path("api/quadros/<int:quadro_id>/colunas/", views.criar_coluna),
    path("api/colunas/<int:coluna_id>/", views.coluna_detalhe),
    path("api/cards/", views.criar_card),
    path("api/cards/<int:card_id>/", views.card_detalhe),
    path("api/cards/<int:card_id>/mover/", views.mover_card),
    path("api/cards/<int:card_id>/atividades/", views.atividades_do_card),
    path("api/cards/<int:card_id>/checklist/", views.criar_item),
    path("api/checklist/<int:item_id>/", views.item_detalhe),
    path("api/colunas/<int:coluna_id>/mover/", views.mover_coluna),
]

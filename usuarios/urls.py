from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    # Acesso
    path("contas/entrar/", auth_views.LoginView.as_view(
        template_name="usuarios/login.html",
        authentication_form=LoginForm,
        redirect_authenticated_user=True,
    ), name="login"),
    path("contas/sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("contas/senha/", views.trocar_senha, name="trocar_senha"),
    path("contas/perfil/", views.perfil, name="perfil"),

    # Usuários
    path("usuarios/", views.lista_usuarios, name="usuarios_lista"),
    path("usuarios/novo/", views.criar_usuario, name="usuario_criar"),
    path("usuarios/<int:usuario_id>/", views.usuario_detalhe, name="usuario_detalhe"),
    path("usuarios/<int:usuario_id>/senha/", views.usuario_senha, name="usuario_senha"),
    path("usuarios/<int:usuario_id>/ativacao/", views.usuario_ativacao, name="usuario_ativacao"),
    path("usuarios/<int:usuario_id>/cargo/", views.usuario_cargo, name="usuario_cargo"),
    path("usuarios/<int:usuario_id>/transferir/", views.usuario_transferir, name="usuario_transferir"),

    # Andares e convites
    path("andares/", views.painel_andares, name="andares"),
    path("convites/", views.convites, name="convites"),
    path("convites/<int:convite_id>/<str:acao>/", views.responder_convite, name="convite_responder"),
]

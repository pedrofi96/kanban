from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse


class TrocaSenhaObrigatoriaMiddleware:
    """Quem está com senha provisória só consegue acessar a tela de trocar
    a senha (e o botão de sair) até definir uma senha nova."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated and usuario.deve_trocar_senha:
            liberadas = {reverse("trocar_senha"), reverse("logout")}
            if request.path not in liberadas and not request.path.startswith("/static/"):
                if request.path.startswith("/api/"):
                    return JsonResponse({"erro": "Troque sua senha provisória antes de continuar."}, status=403)
                return redirect("trocar_senha")
        return self.get_response(request)

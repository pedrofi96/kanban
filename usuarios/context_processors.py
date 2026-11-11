from .models import ConviteTransferencia


def menu(request):
    """Disponível em todo template: número de convites pendentes para o badge do menu."""
    usuario = getattr(request, "user", None)
    if not (usuario and usuario.is_authenticated and usuario.is_admin_andar):
        return {}
    return {
        "convites_pendentes": ConviteTransferencia.objects.filter(
            convidado=usuario, status=ConviteTransferencia.Status.PENDENTE
        ).count()
    }

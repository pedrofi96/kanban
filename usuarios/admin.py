from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Andar, ConviteTransferencia, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "get_full_name", "email", "cargo", "andar", "is_active")
    list_filter = ("cargo", "andar", "is_active", "is_superuser")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("first_name", "last_name")

    fieldsets = UserAdmin.fieldsets + (
        ("Kanban", {"fields": ("cargo", "andar")}),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Dados", {"fields": ("first_name", "last_name", "email", "cargo", "andar")}),
    )


@admin.register(Andar)
class AndarAdmin(admin.ModelAdmin):
    list_display = ("numero", "__str__")
    ordering = ("numero",)


@admin.register(ConviteTransferencia)
class ConviteTransferenciaAdmin(admin.ModelAdmin):
    list_display = (
        "convidado",
        "convidado_por",
        "andar_origem",
        "andar_destino",
        "status",
        "criado_em",
    )
    list_filter = ("status", "andar_destino")
    readonly_fields = ("criado_em", "respondido_em")
from django.contrib import admin

from .models import AtividadeCard, Card, ChecklistItem, Coluna, MembroQuadro, Quadro


class ColunaInline(admin.TabularInline):
    model = Coluna
    extra = 0


class MembroInline(admin.TabularInline):
    model = MembroQuadro
    fk_name = "quadro"
    extra = 0
    autocomplete_fields = ["usuario"]
    readonly_fields = ["adicionado_por", "adicionado_em"]


class ChecklistInline(admin.TabularInline):
    model = ChecklistItem
    extra = 0


class AtividadeInline(admin.TabularInline):
    model = AtividadeCard
    extra = 0
    readonly_fields = ["usuario", "tipo", "descricao", "criado_em"]
    can_delete = False


@admin.register(Quadro)
class QuadroAdmin(admin.ModelAdmin):
    list_display = ["nome", "andar", "criado_em"]
    list_filter = ["andar"]
    search_fields = ["nome"]
    inlines = [MembroInline, ColunaInline]


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ["titulo", "coluna", "prioridade", "responsavel", "vencimento"]
    list_filter = ["prioridade", "coluna__quadro"]
    search_fields = ["titulo"]
    inlines = [ChecklistInline, AtividadeInline]

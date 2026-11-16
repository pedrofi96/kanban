from django.db import migrations, models
from django.utils import timezone


def calcular_status(apps, schema_editor):
    """Preenche o status dos projetos que já existem.
    Concluído = tem pelo menos 1 card e todos estão na coluna "Concluído"."""
    Quadro = apps.get_model("kanban", "Quadro")
    Card = apps.get_model("kanban", "Card")
    for quadro in Quadro.objects.all():
        cards = Card.objects.filter(coluna__quadro=quadro)
        if cards.exists() and not cards.filter(coluna__concluida=False).exists():
            quadro.concluido = True
            quadro.concluido_em = timezone.now()
            quadro.save(update_fields=["concluido", "concluido_em"])


class Migration(migrations.Migration):

    dependencies = [
        ("kanban", "0002_usuarios_e_membros"),
    ]

    operations = [
        migrations.AddField(
            model_name="quadro",
            name="concluido",
            field=models.BooleanField(db_index=True, default=False, editable=False, verbose_name="concluído"),
        ),
        migrations.AddField(
            model_name="quadro",
            name="concluido_em",
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name="concluído em"),
        ),
        # Voltar a migration só remove os campos: não há o que desfazer nos dados.
        migrations.RunPython(calcular_status, migrations.RunPython.noop),
    ]

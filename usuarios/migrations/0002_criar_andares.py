from django.db import migrations


def criar_andares(apps, schema_editor):
    Andar = apps.get_model("usuarios", "Andar")
    for numero in range(1, 6):
        Andar.objects.get_or_create(numero=numero)


def remover_andares(apps, schema_editor):
    Andar = apps.get_model("usuarios", "Andar")
    Andar.objects.filter(numero__in=range(1, 6)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(criar_andares, remover_andares),
    ]
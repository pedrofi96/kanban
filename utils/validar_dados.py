from django.core.exceptions import ValidationError


def email_prefeitura_validar(email_prefeitura):
    if not email_prefeitura.strip().lower().endswith("@salvador.ba.gov.br"):
        raise ValidationError("Use um e-mail institucional (@salvador.ba.gov.br)")

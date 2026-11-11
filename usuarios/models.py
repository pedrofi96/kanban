from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator , MinValueValidator
from django.db import models
from utils.validar_dados import email_prefeitura_validar


# Create your models here.
class Andar (models.Model):
    numero = models.PositiveSmallIntegerField(
        "número",
        unique=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    class Meta:
        ordering = ['numero']
        verbose_name = "andar"
        verbose_name_plural = "andares"
        constraints = [
            models.CheckConstraint(
                condition = models.Q(numero__gte=1) & models.Q(numero__lte=5),
                name= "andar_numero_entre_1_e_5"
            )
        ]
    def __str__(self):
        return f"{self.numero}° andar"

class Usuario (AbstractUser):

    class Cargo(models.TextChoices):
        ADMIN_GERAL = "admin_geral", "Administrador Geral"
        ADMIN_ANDAR ="admin_andar", "Administrador do Andar"
        USUARIO = "usuario", "Usuário"

    cargo = models.CharField(
        max_length=20,
        choices=Cargo.choices,
        default=Cargo.USUARIO,
    )

    andar = models.ForeignKey(
        Andar,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="usuarios",
    )

    email = models.EmailField(
        "e-mail",
        unique=True,
        validators=[email_prefeitura_validar],
    )

    # Ligado quando o admin cria o usuário ou redefine a senha (senha provisória).
    # O middleware obriga a troca no próximo login.
    deve_trocar_senha = models.BooleanField(
        "deve trocar a senha",
        default=False,
    )

    class Meta:
        ordering = ["first_name", "last_name"]
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def is_admin_geral(self):
        return self.cargo == self.Cargo.ADMIN_GERAL

    @property
    def is_admin_andar(self):
        return self.cargo == self.Cargo.ADMIN_ANDAR

    @property
    def is_administrador(self):
        """Qualquer um que gerencia pessoas: superuser, admin geral ou admin do andar."""
        return self.is_superuser or self.is_admin_geral or self.is_admin_andar

    # ---------- Exibição (avatar no quadro) ----------

    CORES_AVATAR = [
        "#ec4899", "#3b82f6", "#8b5cf6", "#14b8a6",
        "#f97316", "#22c55e", "#ef4444", "#0ea5e9",
    ]

    @property
    def nome_exibicao(self):
        return self.get_full_name() or self.username

    @property
    def iniciais(self):
        partes = self.nome_exibicao.split()
        return "".join(p[0] for p in partes[:2]).upper()

    @property
    def cor(self):
        return self.CORES_AVATAR[(self.pk or 0) % len(self.CORES_AVATAR)]

    def to_dict(self):
        return {
            "id": self.pk,
            "nome": self.nome_exibicao,
            "iniciais": self.iniciais,
            "cor": self.cor,
            "andar": self.andar.numero if self.andar_id else None,
            "andar_id": self.andar_id,
        }

    def clean(self):
        super().clean()
        if not self.is_superuser and self.andar_id is None:
            raise ValidationError({"andar":"Todo usuário precisa pertencer a um andar."})

class ConviteTransferencia(models.Model):

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        ACEITO = "aceito", "Aceito"
        RECUSADO = "recusado", "Recusado"
        CANCELADO = "cancelado", "Cancelado"

    convidado = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="convites_recebidos",
    )
    convidado_por = models.ForeignKey(
        Usuario,
        on_delete=models.PROTECT,
        related_name="convites_enviados",
    )

    andar_origem = models.ForeignKey(
        Andar,
        on_delete=models.PROTECT,
        related_name="+"
    )

    andar_destino = models.ForeignKey(
        Andar,
        on_delete=models.PROTECT,
        related_name="convites_recebidos"
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    respondido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "convite de transferência"
        verbose_name_plural = "convites de transferência"
        constraints = [
            models.UniqueConstraint(
                fields=["convidado"],
                condition= models.Q(status="pendente"),
                name="um_convite_por_pessoa",
            ),
            models.CheckConstraint(
                condition =~models.Q(andar_origem=models.F("andar_destino")),
                name="convite_andares_diferentes"
            ),
        ]

    def __str__(self):
        return f"{self.convidado} → {self.andar_destino} ({self.get_status_display()}) "
from django.conf import settings
from django.db import models

COLUNAS_PADRAO = [
    ("A Fazer", False),
    ("Em Progresso", False),
    ("Em Revisão", False),
    ("Concluído", True),
]


class Quadro(models.Model):
    """Projeto. Todo projeto pertence a um andar e tem membros (de qualquer andar)."""

    nome = models.CharField(max_length=120)
    andar = models.ForeignKey(
        "usuarios.Andar",
        on_delete=models.PROTECT,
        related_name="quadros",
    )
    membros = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="MembroQuadro",
        through_fields=("quadro", "usuario"),
        related_name="quadros",
        blank=True,
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    # Status calculado: todos os cards na coluna "Concluído" (e pelo menos 1 card).
    # Não edite à mão: quem mantém é services.atualizar_status_do_quadro.
    concluido = models.BooleanField("concluído", default=False, db_index=True, editable=False)
    concluido_em = models.DateTimeField("concluído em", null=True, blank=True, editable=False)

    class Meta:
        ordering = ["id"]
        verbose_name = "projeto"
        verbose_name_plural = "projetos"

    def __str__(self):
        return self.nome

    def criar_colunas_padrao(self):
        for ordem, (titulo, concluida) in enumerate(COLUNAS_PADRAO):
            Coluna.objects.create(quadro=self, titulo=titulo, ordem=ordem, concluida=concluida)

    def to_dict(self):
        colunas = list(self.colunas.all())
        cards = (
            Card.objects.filter(coluna__quadro=self)
            .prefetch_related("checklist")
            .order_by("coluna__ordem", "ordem")
        )
        return {
            "id": self.id,
            "nome": self.nome,
            "andar_id": self.andar_id,
            "andar": str(self.andar),
            "concluido": self.concluido,
            "membros": [u.to_dict() for u in self.membros.select_related("andar")],
            "colunas": [c.to_dict() for c in colunas],
            "cards": [c.to_dict() for c in cards],
        }


class MembroQuadro(models.Model):
    """Ligação usuário ↔ projeto, guardando quem adicionou e quando."""

    quadro = models.ForeignKey(Quadro, on_delete=models.CASCADE, related_name="participacoes")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="participacoes",
    )
    adicionado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    adicionado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "membro do projeto"
        verbose_name_plural = "membros do projeto"
        constraints = [
            models.UniqueConstraint(fields=["quadro", "usuario"], name="membro_unico_por_quadro"),
        ]

    def __str__(self):
        return f"{self.usuario} em {self.quadro}"


class Coluna(models.Model):
    quadro = models.ForeignKey(Quadro, on_delete=models.CASCADE, related_name="colunas")
    titulo = models.CharField(max_length=60)
    ordem = models.PositiveIntegerField(default=0)
    concluida = models.BooleanField(default=False, help_text="Cards aqui não aparecem como vencidos")

    class Meta:
        ordering = ["ordem"]

    def __str__(self):
        return f"{self.quadro} / {self.titulo}"

    def to_dict(self):
        return {"id": self.id, "titulo": self.titulo, "ordem": self.ordem, "concluida": self.concluida}


class Card(models.Model):
    class Prioridade(models.TextChoices):
        ALTA = "alta", "Alta"
        MEDIA = "media", "Média"
        BAIXA = "baixa", "Baixa"

    coluna = models.ForeignKey(Coluna, on_delete=models.CASCADE, related_name="cards")
    titulo = models.CharField(max_length=200)
    descricao = models.TextField(blank=True)
    prioridade = models.CharField(max_length=10, choices=Prioridade.choices, default=Prioridade.MEDIA)
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cards_responsavel",
    )
    vencimento = models.DateField(null=True, blank=True)
    ordem = models.PositiveIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordem"]

    def __str__(self):
        return self.titulo

    def to_dict(self):
        return {
            "id": self.id,
            "coluna_id": self.coluna_id,
            "titulo": self.titulo,
            "descricao": self.descricao,
            "prioridade": self.prioridade,
            "responsavel_id": self.responsavel_id,
            "vencimento": self.vencimento.isoformat() if self.vencimento else None,
            "ordem": self.ordem,
            "checklist": [i.to_dict() for i in self.checklist.all()],
        }


class AtividadeCard(models.Model):
    """Histórico do card: fica mesmo quando a pessoa sai do projeto."""

    class Tipo(models.TextChoices):
        CRIADO = "criado", "Criou o card"
        MOVIDO = "movido", "Moveu o card"
        RESPONSAVEL = "responsavel", "Mudou o responsável"
        SAIU_DO_PROJETO = "saiu_do_projeto", "Responsável saiu do projeto"

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="atividades")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="atividades",
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    descricao = models.CharField(max_length=255)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "-id"]
        verbose_name = "atividade do card"
        verbose_name_plural = "atividades do card"

    def __str__(self):
        return self.descricao

    def to_dict(self):
        return {
            "id": self.id,
            "tipo": self.tipo,
            "descricao": self.descricao,
            "usuario": self.usuario.nome_exibicao if self.usuario_id else "—",
            "criado_em": self.criado_em.isoformat(),
        }


class ChecklistItem(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="checklist")
    texto = models.CharField(max_length=200)
    feito = models.BooleanField(default=False)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "id"]

    def __str__(self):
        return self.texto

    def to_dict(self):
        return {"id": self.id, "texto": self.texto, "feito": self.feito}

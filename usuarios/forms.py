from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

from . import permissoes
from .models import Andar, Usuario

# Mesmo visual dos campos do quadro (Tailwind).
CLASSE_CAMPO = (
    "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition "
    "focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 "
    "dark:border-slate-700 dark:bg-slate-800 dark:[color-scheme:dark]"
)


class EstiloMixin:
    """Coloca a classe Tailwind em todos os campos do formulário."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            if not isinstance(campo.widget, forms.CheckboxInput):
                campo.widget.attrs.setdefault("class", CLASSE_CAMPO)


# ----------------------------------------------------------------------
# Acesso
# ----------------------------------------------------------------------

class LoginForm(EstiloMixin, AuthenticationForm):
    error_messages = {
        "invalid_login": "Usuário ou senha incorretos.",
        "inactive": "Esta conta está desativada. Procure o administrador do seu andar.",
    }


class TrocarSenhaForm(EstiloMixin, PasswordChangeForm):
    pass


class PerfilForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["first_name", "last_name", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True


# ----------------------------------------------------------------------
# Gestão de usuários
# ----------------------------------------------------------------------

class CriarUsuarioForm(EstiloMixin, forms.ModelForm):
    senha_provisoria = forms.CharField(
        label="Senha provisória",
        help_text="Pode ser simples (ex.: 123). A pessoa troca no primeiro acesso.",
    )

    class Meta:
        model = Usuario
        fields = ["first_name", "last_name", "username", "email", "andar", "cargo"]

    def __init__(self, *args, ator, **kwargs):
        super().__init__(*args, **kwargs)
        self.ator = ator
        self.fields["first_name"].required = True
        self.fields["andar"].required = True
        self.fields["andar"].empty_label = None

        cargos = permissoes.cargos_que_pode_atribuir(ator)
        self.fields["cargo"].choices = [(c.value, c.label) for c in cargos]

        if permissoes.tem_poder_global(ator):
            self.fields["andar"].queryset = Andar.objects.all()
            if ator.andar_id:
                self.fields["andar"].initial = ator.andar_id
        else:
            # Admin do andar só cria no próprio andar.
            self.fields["andar"].queryset = Andar.objects.filter(pk=ator.andar_id)
            self.fields["andar"].initial = ator.andar_id

    def clean(self):
        dados = super().clean()
        andar, cargo = dados.get("andar"), dados.get("cargo")
        if andar and cargo and not permissoes.pode_criar_usuario(self.ator, andar, cargo):
            raise forms.ValidationError("Você não pode criar um usuário com esse cargo nesse andar.")
        return dados


class EditarUsuarioForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["first_name", "last_name", "username", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True


class RedefinirSenhaForm(EstiloMixin, forms.Form):
    senha_provisoria = forms.CharField(
        label="Nova senha provisória",
        help_text="A pessoa será obrigada a trocar no próximo acesso.",
    )


class AlterarCargoForm(EstiloMixin, forms.Form):
    cargo = forms.ChoiceField(label="Cargo")

    def __init__(self, *args, ator, alvo, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cargo"].choices = [
            (c.value, c.label) for c in permissoes.cargos_que_pode_atribuir(ator)
        ]
        self.fields["cargo"].initial = alvo.cargo


class TransferirForm(EstiloMixin, forms.Form):
    andar = forms.ModelChoiceField(label="Novo andar", queryset=Andar.objects.none(), empty_label=None)

    def __init__(self, *args, alvo, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["andar"].queryset = Andar.objects.exclude(pk=alvo.andar_id)


class ConvidarForm(EstiloMixin, forms.Form):
    convidado = forms.ModelChoiceField(
        label="Administrador a convidar",
        queryset=Usuario.objects.none(),
        empty_label="Selecione…",
    )

    def __init__(self, *args, ator, **kwargs):
        super().__init__(*args, **kwargs)
        self.ator = ator
        self.fields["convidado"].queryset = (
            Usuario.objects.filter(
                is_active=True, cargo=Usuario.Cargo.ADMIN_ANDAR, andar__isnull=False
            )
            .exclude(andar_id=ator.andar_id)
            .select_related("andar")
            .order_by("andar__numero", "first_name")
        )
        self.fields["convidado"].label_from_instance = lambda u: f"{u.nome_exibicao} ({u.andar})"

    def clean_convidado(self):
        convidado = self.cleaned_data["convidado"]
        if not permissoes.pode_convidar(self.ator, convidado):
            raise forms.ValidationError("Essa pessoa não pode ser convidada agora (já tem um convite pendente?).")
        return convidado

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm

from .models import AuthChallenge, User
from .otp import available_2fa_channels, find_user_by_identifier
from .phone import normalize_phone


class IdentifierAuthenticationForm(AuthenticationForm):
    """Connexion par e-mail, téléphone ou nom d’utilisateur + mot de passe."""

    username = forms.CharField(
        label="E-mail, téléphone ou identifiant",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "username",
                "placeholder": "vous@exemple.fr ou 06…",
            }
        ),
    )

    def clean(self):
        identifier = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if identifier and password:
            user = find_user_by_identifier(identifier)
            if user is None:
                raise forms.ValidationError(
                    "Identifiant ou mot de passe incorrect.",
                    code="invalid_login",
                )
            self.user_cache = authenticate(
                self.request,
                username=user.get_username(),
                password=password,
            )
            if self.user_cache is None:
                raise forms.ValidationError(
                    "Identifiant ou mot de passe incorrect.",
                    code="invalid_login",
                )
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


class PasswordlessStartForm(forms.Form):
    identifier = forms.CharField(
        label="E-mail ou téléphone",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "username",
                "placeholder": "vous@exemple.fr ou 06…",
            }
        ),
    )
    channel = forms.ChoiceField(
        label="Recevoir le code par",
        choices=[
            (AuthChallenge.Channel.EMAIL, "E-mail"),
            (AuthChallenge.Channel.SMS, "SMS"),
        ],
        initial=AuthChallenge.Channel.EMAIL,
        widget=forms.RadioSelect,
    )

    def clean(self):
        cleaned = super().clean()
        identifier = cleaned.get("identifier", "")
        channel = cleaned.get("channel")
        user = find_user_by_identifier(identifier)
        # Ne pas révéler si le compte existe ; la vue gère l’absence.
        if user is not None:
            if channel == AuthChallenge.Channel.EMAIL and not user.email:
                user = None
            elif channel == AuthChallenge.Channel.SMS and not normalize_phone(user.phone):
                user = None
        cleaned["user"] = user
        return cleaned


class OTPVerifyForm(forms.Form):
    code = forms.CharField(
        label="Code à 6 chiffres",
        max_length=8,
        min_length=6,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "placeholder": "123456",
                "class": "otp-input",
            }
        ),
    )
    challenge_id = forms.UUIDField(widget=forms.HiddenInput)
    pending_token = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_code(self):
        return self.cleaned_data["code"].strip().replace(" ", "")


class TwoFactorChannelForm(forms.Form):
    channel = forms.ChoiceField(label="Canal", widget=forms.RadioSelect)

    def __init__(self, user: User, *args, **kwargs):
        super().__init__(*args, **kwargs)
        channels = available_2fa_channels(user)
        labels = dict(AuthChallenge.Channel.choices)
        self.fields["channel"].choices = [(c, labels.get(c, c)) for c in channels]
        if user.preferred_2fa_channel in channels:
            self.fields["channel"].initial = user.preferred_2fa_channel
        elif channels:
            self.fields["channel"].initial = channels[0]


class ProfileSecurityForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("preferred_2fa_channel", "two_factor_enabled")
        labels = {
            "preferred_2fa_channel": "Canal de double authentification préféré",
            "two_factor_enabled": "Activer la double authentification",
        }


class ChatNotificationPrefsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("chat_auto_subscribe",)
        labels = {
            "chat_auto_subscribe": "M’abonner automatiquement aux salons des nouveaux événements",
        }
        help_texts = {
            "chat_auto_subscribe": (
                "Vous recevrez un digest des nouveaux messages (notification push "
                "si activée, sinon e-mail). Vous pourrez vous désabonner salon par salon."
            ),
        }

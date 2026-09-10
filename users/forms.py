from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm

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
            (AuthChallenge.Channel.NOTIFICATION, "Notification"),
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
            elif channel == AuthChallenge.Channel.NOTIFICATION and not normalize_phone(user.phone):
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


class NewPasswordForm(SetPasswordForm):
    """Nouveau mot de passe sans ressaisir l’ancien (premier accès ou reprise en main)."""

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["new_password1"].label = "Nouveau mot de passe"
        self.fields["new_password2"].label = "Confirmation"
        self.fields["new_password1"].widget.attrs["autofocus"] = True

    def clean(self):
        cleaned = super().clean()
        new = cleaned.get("new_password2") or cleaned.get("new_password1")
        if new and self.user.check_password(new):
            self.add_error(
                "new_password1",
                "Choisissez un mot de passe différent du mot de passe actuel.",
            )
        return cleaned


class ProfileSecurityForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("preferred_2fa_channel", "two_factor_enabled")
        labels = {
            "preferred_2fa_channel": "Canal de double authentification préféré",
            "two_factor_enabled": "Activer la double authentification",
        }


class NotificationPrefsForm(forms.ModelForm):
    """Défaut de fréquence + abonnement auto aux salons."""

    class Meta:
        model = User
        fields = (
            "notify_frequency",
            "notify_digest_hour",
            "notify_digest_weekday",
            "chat_auto_subscribe",
        )
        labels = {
            "notify_frequency": "Fréquence par défaut",
            "notify_digest_hour": "Heure du récap",
            "notify_digest_weekday": "Jour du récap hebdomadaire",
            "chat_auto_subscribe": (
                "M’abonner automatiquement aux salons des nouveaux événements"
            ),
        }
        help_texts = {
            "notify_frequency": (
                "S’applique à toutes les alertes sauf exception ci-dessous. "
                "Temps réel : tout de suite (messages de salon regroupés ~toutes "
                "les 30 min). Les @mentions restent toujours immédiates ; "
                "les réponses à vos messages ont leur propre réglage."
            ),
            "chat_auto_subscribe": (
                "Vous pourrez désactiver les alertes salon par salon, "
                "ou choisir une autre fréquence ci-dessous."
            ),
        }
        widgets = {
            "notify_frequency": forms.RadioSelect,
            "notify_digest_hour": forms.Select,
            "notify_digest_weekday": forms.Select,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from users.notify_prefs import HOUR_CHOICES, WEEKDAY_LABELS

        self.fields["notify_digest_hour"].choices = HOUR_CHOICES
        self.fields["notify_digest_weekday"].choices = WEEKDAY_LABELS
        self.fields["notify_digest_hour"].widget.choices = HOUR_CHOICES
        self.fields["notify_digest_weekday"].widget.choices = WEEKDAY_LABELS

    def clean(self):
        cleaned = super().clean()
        freq = cleaned.get("notify_frequency")
        if freq and freq != User.NotifyFrequency.REALTIME:
            if cleaned.get("notify_digest_hour") is None:
                self.add_error(
                    "notify_digest_hour",
                    "Indiquez l’heure du récap.",
                )
        if freq == User.NotifyFrequency.WEEKLY:
            if cleaned.get("notify_digest_weekday") is None:
                self.add_error(
                    "notify_digest_weekday",
                    "Indiquez le jour du récap hebdomadaire.",
                )
        return cleaned


# Rétro-compat imports / tests
ChatNotificationPrefsForm = NotificationPrefsForm


class StaffContactNotifyPrefsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("notify_contact_messages",)
        labels = {
            "notify_contact_messages": "M’alerter des nouveaux messages de contact / prestations",
        }
        help_texts = {
            "notify_contact_messages": (
                "Notification push si activée, sinon e-mail, pour chaque demande "
                "reçue via le formulaire public. La fréquence se règle dans "
                "Préférences de notifications."
            ),
        }

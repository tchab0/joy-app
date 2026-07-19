"""Formulaires admin pour la gestion des musiciens."""

from __future__ import annotations

import re
import unicodedata

from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction

from planning.models import MusicianProfile
from users.roles import sync_user_groups

User = get_user_model()

_INPUT = {"class": "field-input"}
_SELECT = {"class": "field-input"}


def _slugify_username(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", ".", value.strip().lower())
    return value.strip(".")[:40] or "musicien"


def _unique_username(base: str) -> str:
    candidate = base
    n = 1
    while User.objects.filter(username=candidate).exists():
        n += 1
        candidate = f"{base}.{n}"
    return candidate


class MusicianAdminForm(forms.Form):
    first_name = forms.CharField(
        label="Prénom",
        max_length=150,
        widget=forms.TextInput(attrs=_INPUT),
    )
    last_name = forms.CharField(
        label="Nom",
        max_length=150,
        widget=forms.TextInput(attrs=_INPUT),
    )
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs=_INPUT),
    )
    phone = forms.CharField(
        label="Téléphone",
        max_length=20,
        required=False,
        widget=forms.TextInput(
            attrs={**_INPUT, "placeholder": "+33612345678"}
        ),
    )
    poste_titulaire = forms.ChoiceField(
        label="Poste titulaire",
        choices=[("", "— Non titulaire —")] + list(MusicianProfile.Poste.choices),
        required=False,
        widget=forms.Select(attrs=_SELECT),
        help_text="Convoqué à chaque nouvelle date. Le pupitre en découle automatiquement.",
    )
    poste_remplacant = forms.ChoiceField(
        label="Poste remplaçant",
        choices=[("", "— Non remplaçant —")] + list(MusicianProfile.Poste.choices),
        required=False,
        widget=forms.Select(attrs=_SELECT),
        help_text="Sollicité en cas de besoin sur ce poste.",
    )
    is_active = forms.BooleanField(
        label="Compte actif",
        required=False,
        initial=True,
    )

    def __init__(self, *args, profile: MusicianProfile | None = None, **kwargs):
        self.profile = profile
        self.user = profile.user if profile else None
        super().__init__(*args, **kwargs)
        if profile is not None:
            user = profile.user
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email
            self.fields["phone"].initial = user.phone
            self.fields["poste_titulaire"].initial = profile.poste_titulaire
            self.fields["poste_remplacant"].initial = profile.poste_remplacant
            self.fields["is_active"].initial = user.is_active

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.user is not None:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("Un compte existe déjà avec cet e-mail.")
        return email

    def clean(self):
        cleaned = super().clean()
        tit = (cleaned.get("poste_titulaire") or "").strip()
        rem = (cleaned.get("poste_remplacant") or "").strip()
        if tit and rem and tit == rem:
            raise forms.ValidationError(
                "Le poste titulaire et le poste remplaçant doivent être différents "
                "(un musicien peut cumuler les deux rôles sur des chaises distinctes)."
            )
        cleaned["poste_titulaire"] = tit
        cleaned["poste_remplacant"] = rem
        return cleaned

    @transaction.atomic
    def save(self) -> MusicianProfile:
        data = self.cleaned_data
        if self.user is None:
            base = _slugify_username(
                f"{data['first_name']}.{data['last_name']}"
            ) or _slugify_username(data["email"].split("@")[0])
            user = User(
                username=_unique_username(base),
                email=data["email"],
                first_name=data["first_name"].strip(),
                last_name=data["last_name"].strip(),
                phone=(data.get("phone") or "").strip(),
                is_musician=True,
                is_active=bool(data.get("is_active", True)),
            )
            user.set_unusable_password()
            user.save()
            sync_user_groups(user)
            profile = MusicianProfile(user=user)
        else:
            user = self.user
            user.first_name = data["first_name"].strip()
            user.last_name = data["last_name"].strip()
            user.email = data["email"]
            user.phone = (data.get("phone") or "").strip()
            user.is_musician = True
            user.is_active = bool(data.get("is_active", True))
            user.save()
            sync_user_groups(user)
            profile = self.profile

        profile.poste_titulaire = data["poste_titulaire"]
        profile.poste_remplacant = data["poste_remplacant"]
        profile.save()  # sync_section_from_poste via MusicianProfile.save
        return profile

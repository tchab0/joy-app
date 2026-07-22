from django import forms

from repetitions.services import (
    DEFAULT_REHEARSAL_VENUE_NOM,
    is_default_rehearsal_venue,
)


class RehearsalCreateForm(forms.Form):
    """Création : lieu par défaut Mingus, ou saisie manuelle (pas les salles concerts)."""

    titre = forms.CharField(label="Titre", max_length=300)
    date = forms.DateField(
        label="Date",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    time_start = forms.TimeField(
        label="Début",
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        input_formats=["%H:%M", "%H:%M:%S"],
        initial="20:15",
    )
    time_end = forms.TimeField(
        label="Fin",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        input_formats=["%H:%M", "%H:%M:%S"],
    )
    venue_mode = forms.ChoiceField(
        label="Lieu",
        choices=[
            ("default", DEFAULT_REHEARSAL_VENUE_NOM),
            ("custom", "Autre lieu"),
        ],
        initial="default",
        widget=forms.HiddenInput,
    )
    venue_nom = forms.CharField(label="Nom du lieu", max_length=200, required=False)
    venue_ville = forms.CharField(label="Ville", max_length=100, required=False)
    venue_adresse = forms.CharField(label="Adresse", max_length=300, required=False)
    description = forms.CharField(
        label="Description",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    notes = forms.CharField(
        label="Notes feuille de route",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    notify_musicians = forms.BooleanField(
        label="Notifier les musiciens",
        required=False,
        initial=True,
    )

    def clean(self):
        cleaned = super().clean()
        return _clean_rehearsal_venue(self, cleaned)


class RehearsalEditForm(forms.Form):
    titre = forms.CharField(label="Titre", max_length=300)
    date = forms.DateField(
        label="Date",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    time_start = forms.TimeField(
        label="Début",
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        input_formats=["%H:%M", "%H:%M:%S"],
    )
    time_end = forms.TimeField(
        label="Fin",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        input_formats=["%H:%M", "%H:%M:%S"],
    )
    venue_mode = forms.ChoiceField(
        label="Lieu",
        choices=[
            ("default", DEFAULT_REHEARSAL_VENUE_NOM),
            ("custom", "Autre lieu"),
        ],
        initial="default",
        widget=forms.HiddenInput,
    )
    venue_nom = forms.CharField(label="Nom du lieu", max_length=200, required=False)
    venue_ville = forms.CharField(label="Ville", max_length=100, required=False)
    venue_adresse = forms.CharField(label="Adresse", max_length=300, required=False)
    description = forms.CharField(
        label="Description",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    notes = forms.CharField(
        label="Notes feuille de route",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    statut = forms.ChoiceField(
        label="Statut",
        choices=[
            ("confirme", "Confirmé"),
            ("tentative", "Date à confirmer"),
            ("annule", "Annulé"),
        ],
    )

    def clean(self):
        cleaned = super().clean()
        return _clean_rehearsal_venue(self, cleaned)


def _clean_rehearsal_venue(form, cleaned: dict) -> dict:
    mode = (cleaned.get("venue_mode") or "default").strip()
    if mode == "custom":
        nom = (cleaned.get("venue_nom") or "").strip()
        ville = (cleaned.get("venue_ville") or "").strip()
        if not nom:
            form.add_error("venue_nom", "Indiquez le nom du lieu.")
        if not ville:
            form.add_error("venue_ville", "Indiquez la ville.")
        cleaned["venue_nom"] = nom
        cleaned["venue_ville"] = ville
        cleaned["venue_adresse"] = (cleaned.get("venue_adresse") or "").strip()
    return cleaned


def venue_initial_from_event(venue) -> dict:
    """Préremplit le bloc lieu (défaut Mingus ou autre)."""
    if venue is None or is_default_rehearsal_venue(venue):
        return {"venue_mode": "default"}
    return {
        "venue_mode": "custom",
        "venue_nom": venue.nom,
        "venue_ville": venue.ville,
        "venue_adresse": venue.adresse or "",
    }

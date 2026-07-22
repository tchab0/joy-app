from django import forms

from events.models import Venue


class RehearsalCreateForm(forms.Form):
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
        initial="20:00",
    )
    time_end = forms.TimeField(
        label="Fin",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        input_formats=["%H:%M", "%H:%M:%S"],
    )
    venue = forms.ModelChoiceField(
        label="Lieu",
        queryset=Venue.objects.all().order_by("ville", "nom"),
    )
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
        initial=False,
    )


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
    venue = forms.ModelChoiceField(
        label="Lieu",
        queryset=Venue.objects.all().order_by("ville", "nom"),
    )
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

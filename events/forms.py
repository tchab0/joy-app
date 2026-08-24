from django import forms
from django.db.models import Q
from .models import Event, Venue, EventType
from .organisme import organisme_url_for_name, remember_organisme


class VenueForm(forms.ModelForm):
    class Meta:
        model = Venue
        fields = ['nom', 'adresse', 'ville', 'latitude', 'longitude']
        widgets = {
            'latitude':  forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, f in self.fields.items():
            if name not in ('latitude', 'longitude'):
                f.widget.attrs.setdefault('class', 'field-input')


class EventForm(forms.ModelForm):
    organisme_url = forms.URLField(
        required=False,
        label="Site web de l'organisme",
        help_text="Lien affiché sur le nom de l'organisme (page publique).",
    )

    class Meta:
        model = Event
        fields = [
            'titre', 'slug', 'type', 'venue', 'date_debut', 'date_fin',
            'statut', 'public', 'parent', 'organisme', 'url_billets',
            'contact_nom', 'contact_telephone', 'contact_email',
            'description',
        ]
        widgets = {
            'date_debut':  forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'date_fin':    forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'description': forms.Textarea(attrs={'rows': 3}),
            'organisme': forms.TextInput(attrs={'placeholder': 'ex. Mairie de La Roche-sur-Yon'}),
        }

    def __init__(self, *args, concerts_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        if concerts_only:
            self.fields["type"].queryset = EventType.objects.filter(is_rehearsal=False).exclude(
                Q(nom__icontains="épétition") | Q(nom__icontains="repetition")
            )
        for f in self.fields.values():
            f.widget.attrs.setdefault('class', 'field-input')
        parents = Event.objects.all().order_by('-date_debut')
        if self.instance and self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
            self.fields['date_debut'].initial = self.instance.date_debut.strftime('%Y-%m-%dT%H:%M')
            if self.instance.date_fin:
                self.fields['date_fin'].initial = self.instance.date_fin.strftime('%Y-%m-%dT%H:%M')
            if self.instance.organisme:
                self.fields["organisme_url"].initial = organisme_url_for_name(
                    self.instance.organisme
                )
        self.fields['parent'].queryset = parents
        self.fields['parent'].required = False
        self.fields['parent'].empty_label = "— Aucun —"
        self.fields['slug'].required = False
        self.fields['slug'].help_text = "Laisser vide pour génération automatique."

    def save(self, commit=True):
        event = super().save(commit=commit)
        if commit and event.organisme:
            remember_organisme(event.organisme, self.cleaned_data.get("organisme_url") or "")
        return event

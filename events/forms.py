from django import forms
from .models import Event, Venue, EventType


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault('class', 'field-input')
        parents = Event.objects.all().order_by('-date_debut')
        if self.instance and self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
            self.fields['date_debut'].initial = self.instance.date_debut.strftime('%Y-%m-%dT%H:%M')
            if self.instance.date_fin:
                self.fields['date_fin'].initial = self.instance.date_fin.strftime('%Y-%m-%dT%H:%M')
        self.fields['parent'].queryset = parents
        self.fields['parent'].required = False
        self.fields['parent'].empty_label = "— Aucun —"
        self.fields['slug'].required = False
        self.fields['slug'].help_text = "Laisser vide pour génération automatique."

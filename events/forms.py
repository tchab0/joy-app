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
        fields = ['titre', 'type', 'venue', 'date_debut', 'date_fin',
                  'statut', 'public', 'url_billets', 'description']
        widgets = {
            'date_debut':  forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'date_fin':    forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault('class', 'field-input')
        if self.instance and self.instance.pk:
            self.fields['date_debut'].initial = self.instance.date_debut.strftime('%Y-%m-%dT%H:%M')
            if self.instance.date_fin:
                self.fields['date_fin'].initial = self.instance.date_fin.strftime('%Y-%m-%dT%H:%M')

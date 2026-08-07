from django import forms
from .models import MediaItem, EvenementMedia

MAX_SIZE_BYTES = 1 * 1024 * 1024 * 1024

EXTENSIONS_AUTORISEES = {
    "photo": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
    "audio": [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"],
    "video": [".mp4", ".mov", ".avi", ".mkv", ".webm"],
    "pdf":   [".pdf"],
}


class ContactForm(forms.Form):
    nom = forms.CharField(
        max_length=150,
        label="Nom",
        widget=forms.TextInput(attrs={
            "class": "form-input",
            "autocomplete": "name",
            "placeholder": "Votre nom",
        }),
    )
    telephone = forms.CharField(
        required=False,
        max_length=50,
        label="Téléphone",
        widget=forms.TextInput(attrs={
            "class": "form-input",
            "autocomplete": "tel",
            "placeholder": "06 12 34 56 78",
        }),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={
            "class": "form-input",
            "autocomplete": "email",
            "placeholder": "vous@exemple.fr",
        }),
    )
    message = forms.CharField(
        label="Message",
        widget=forms.Textarea(attrs={
            "class": "form-input",
            "rows": 6,
            "placeholder": "Décrivez votre demande",
        }),
    )

    def clean_nom(self):
        return self.cleaned_data["nom"].strip()

    def clean_telephone(self):
        return self.cleaned_data["telephone"].strip()

    def clean_message(self):
        message = self.cleaned_data["message"].strip()
        if len(message) < 10:
            raise forms.ValidationError("Merci de préciser un peu plus votre demande.")
        return message


class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True

    def value_from_datadict(self, data, files, name):
        return files.getlist(name)


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={
            "class": "form-input",
            "accept": "image/*",
        }))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        return [super(forms.FileField, self).clean(f) for f in data]


class MediaSoumissionForm(forms.ModelForm):
    fichiers_multiples = MultipleFileField(
        required=False,
        label="Photos (sélection multiple possible)",
    )
    evenement_existant = forms.ModelChoiceField(
        queryset=EvenementMedia.objects.all(),
        required=False,
        empty_label="— Choisir un événement existant —",
        label="Événement existant",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    evenement_nouveau = forms.CharField(
        required=False,
        max_length=200,
        label="Ou créer un nouvel événement",
        widget=forms.TextInput(attrs={
            "class": "form-input",
            "placeholder": "Ex : Concert Fête de la Musique 2025",
        }),
    )
    evenement_date = forms.DateField(
        required=False,
        label="Date de l'événement",
        widget=forms.DateInput(attrs={"class": "form-input", "type": "date"}),
    )

    class Meta:
        model = MediaItem
        fields = ["type", "fichier", "url_externe", "soumis_par_nom", "soumis_par_email"]
        labels = {
            "type": "Type de média",
            "fichier": "Fichier (vidéo, audio ou PDF — max 1 Go)",
            "url_externe": "Lien vidéo (YouTube, Vimeo…)",
            "soumis_par_nom": "Votre nom",
            "soumis_par_email": "Votre e-mail (optionnel)",
        }
        widgets = {
            "type": forms.Select(attrs={"class": "form-select", "x-model": "type"}),
            "fichier": forms.FileInput(attrs={"class": "form-input"}),
            "url_externe": forms.URLInput(attrs={"class": "form-input", "placeholder": "https://youtube.com/..."}),
            "soumis_par_nom": forms.TextInput(attrs={"class": "form-input", "placeholder": "Jean Dupont"}),
            "soumis_par_email": forms.EmailInput(attrs={"class": "form-input", "placeholder": "jean@exemple.fr"}),
        }

    def clean(self):
        cleaned = super().clean()
        type_media = cleaned.get("type")
        fichier = cleaned.get("fichier")
        fichiers_multiples = cleaned.get("fichiers_multiples", [])
        url_ext = cleaned.get("url_externe")
        ev_existant = cleaned.get("evenement_existant")
        ev_nouveau = cleaned.get("evenement_nouveau", "").strip()

        if not ev_existant and not ev_nouveau:
            raise forms.ValidationError("Choisissez un événement existant ou créez-en un nouveau.")

        if type_media == "photo":
            for photo in fichiers_multiples or ([fichier] if fichier else []):
                self._validate_upload(photo, type_media)
            return cleaned

        if type_media == "video" and not fichier and not url_ext:
            raise forms.ValidationError("Pour une vidéo, fournissez un fichier ou un lien externe.")

        if type_media not in ("photo", "video") and not fichier:
            raise forms.ValidationError("Veuillez sélectionner un fichier.")

        if fichier:
            self._validate_upload(fichier, type_media)

        return cleaned

    @staticmethod
    def _validate_upload(fichier, type_media):
        if fichier.size > MAX_SIZE_BYTES:
            raise forms.ValidationError("Le fichier dépasse la limite de 1 Go.")

        ext = "." + fichier.name.rsplit(".", 1)[-1].lower() if "." in fichier.name else ""
        exts_ok = EXTENSIONS_AUTORISEES.get(type_media, [])
        if exts_ok and ext not in exts_ok:
            raise forms.ValidationError(f"Extension non autorisée. Acceptées : {', '.join(exts_ok)}")

        if type_media == "photo":
            try:
                forms.ImageField().clean(fichier)
            except forms.ValidationError as exc:
                raise forms.ValidationError("Le fichier sélectionné n'est pas une image valide.") from exc

    def get_or_create_evenement(self):
        ev = self.cleaned_data.get("evenement_existant")
        if ev:
            return ev
        nom = self.cleaned_data.get("evenement_nouveau", "").strip()
        date = self.cleaned_data.get("evenement_date")
        ev, _ = EvenementMedia.objects.get_or_create(nom=nom, defaults={"date": date})
        return ev

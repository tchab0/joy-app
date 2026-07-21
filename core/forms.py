from django import forms

from .models import ContactMessage, MediaItem, EvenementMedia

MAX_SIZE_BYTES = 1 * 1024 * 1024 * 1024

EXTENSIONS_AUTORISEES = {
    "photo": [".jpg", ".jpeg", ".png", ".gif", ".webp"],
    "audio": [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"],
    "video": [".mp4", ".mov", ".avi", ".mkv", ".webm"],
    "pdf":   [".pdf"],
}

_INPUT = {"class": "form-input"}
_SELECT = {"class": "form-select"}
_TEXTAREA = {"class": "form-input", "rows": 4}


class ContactForm(forms.Form):
    nom = forms.CharField(
        max_length=150,
        label="Nom",
        widget=forms.TextInput(attrs={
            **_INPUT,
            "autocomplete": "name",
            "placeholder": "Votre nom",
        }),
    )
    telephone = forms.CharField(
        required=False,
        max_length=50,
        label="Téléphone",
        widget=forms.TextInput(attrs={
            **_INPUT,
            "autocomplete": "tel",
            "placeholder": "06 12 34 56 78",
        }),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={
            **_INPUT,
            "autocomplete": "email",
            "placeholder": "vous@exemple.fr",
        }),
    )
    message = forms.CharField(
        label="Message",
        widget=forms.Textarea(attrs={
            **_INPUT,
            "rows": 6,
            "placeholder": "Décrivez votre demande",
        }),
    )
    rgpd = forms.BooleanField(
        label="J’accepte que mes informations soient utilisées pour traiter ma demande.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check"}),
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


class PrestationForm(forms.Form):
    nom = forms.CharField(
        max_length=150,
        label="Nom",
        widget=forms.TextInput(attrs={
            **_INPUT,
            "autocomplete": "name",
            "placeholder": "Votre nom",
        }),
    )
    organisation = forms.CharField(
        required=False,
        max_length=200,
        label="Organisation",
        widget=forms.TextInput(attrs={
            **_INPUT,
            "placeholder": "Association, entreprise, mairie…",
        }),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={
            **_INPUT,
            "autocomplete": "email",
            "placeholder": "vous@exemple.fr",
        }),
    )
    telephone = forms.CharField(
        max_length=50,
        label="Téléphone",
        widget=forms.TextInput(attrs={
            **_INPUT,
            "autocomplete": "tel",
            "placeholder": "06 12 34 56 78",
        }),
    )
    profil = forms.ChoiceField(
        label="Vous êtes",
        choices=ContactMessage.PROFIL_CHOICES,
        widget=forms.Select(attrs=_SELECT),
    )

    type_evenement = forms.ChoiceField(
        label="Type d’événement",
        choices=ContactMessage.TYPE_EVENEMENT_CHOICES,
        widget=forms.Select(attrs=_SELECT),
    )
    date_souhaitee = forms.DateField(
        label="Date souhaitée",
        widget=forms.DateInput(attrs={**_INPUT, "type": "date"}),
    )
    date_flexible = forms.BooleanField(
        required=False,
        label="La date est flexible",
        widget=forms.CheckboxInput(attrs={"class": "form-check"}),
    )
    date_alternative = forms.DateField(
        required=False,
        label="Autre date possible",
        widget=forms.DateInput(attrs={**_INPUT, "type": "date"}),
    )
    ville = forms.CharField(
        max_length=120,
        label="Ville / commune",
        widget=forms.TextInput(attrs={
            **_INPUT,
            "placeholder": "La Roche-sur-Yon",
        }),
    )
    lieu_nom = forms.CharField(
        required=False,
        max_length=200,
        label="Nom du lieu",
        widget=forms.TextInput(attrs={
            **_INPUT,
            "placeholder": "Salle, salle des fêtes…",
        }),
    )
    lieu_adresse = forms.CharField(
        required=False,
        max_length=300,
        label="Adresse du lieu",
        widget=forms.TextInput(attrs={
            **_INPUT,
            "placeholder": "Adresse si déjà connue",
        }),
    )
    lieu_type = forms.ChoiceField(
        label="Lieu",
        choices=ContactMessage.LIEU_TYPE_CHOICES,
        widget=forms.Select(attrs=_SELECT),
    )
    heure_debut = forms.TimeField(
        label="Début de prestation",
        widget=forms.TimeInput(attrs={**_INPUT, "type": "time"}),
    )
    heure_fin = forms.TimeField(
        required=False,
        label="Fin de prestation",
        widget=forms.TimeInput(attrs={**_INPUT, "type": "time"}),
    )
    duree_jeu = forms.ChoiceField(
        label="Durée de jeu souhaitée",
        choices=ContactMessage.DUREE_CHOICES,
        widget=forms.Select(attrs=_SELECT),
    )
    jauge = forms.ChoiceField(
        label="Public approximatif",
        choices=ContactMessage.JAUGE_CHOICES,
        widget=forms.Select(attrs=_SELECT),
    )
    role_ambiance = forms.ChoiceField(
        label="Rôle / ambiance",
        choices=ContactMessage.ROLE_CHOICES,
        widget=forms.Select(attrs=_SELECT),
    )

    sono = forms.ChoiceField(
        label="Sonorisation",
        choices=ContactMessage.SONO_CHOICES,
        widget=forms.Select(attrs=_SELECT),
    )
    scene_details = forms.CharField(
        required=False,
        label="Scène / espace de jeu",
        widget=forms.Textarea(attrs={
            **_TEXTAREA,
            "placeholder": "Dimensions, hauteur sous plafond, accès…",
        }),
    )
    acces_logistique = forms.CharField(
        required=False,
        label="Accès / parking / déchargement",
        widget=forms.Textarea(attrs={
            **_TEXTAREA,
            "rows": 3,
            "placeholder": "Optionnel",
        }),
    )
    budget = forms.ChoiceField(
        label="Budget indicatif",
        choices=ContactMessage.BUDGET_CHOICES,
        widget=forms.Select(attrs=_SELECT),
    )
    message = forms.CharField(
        required=False,
        label="Demandes particulières",
        widget=forms.Textarea(attrs={
            **_TEXTAREA,
            "rows": 5,
            "placeholder": "Répertoire, dress code, contraintes…",
        }),
    )
    source = forms.ChoiceField(
        required=False,
        label="Comment nous avez-vous connus ?",
        choices=[("", "—")] + list(ContactMessage.SOURCE_CHOICES),
        widget=forms.Select(attrs=_SELECT),
    )
    rgpd = forms.BooleanField(
        label="J’accepte que mes informations soient utilisées pour traiter ma demande.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check"}),
    )

    def clean_nom(self):
        return self.cleaned_data["nom"].strip()

    def clean_organisation(self):
        return self.cleaned_data["organisation"].strip()

    def clean_telephone(self):
        return self.cleaned_data["telephone"].strip()

    def clean_ville(self):
        return self.cleaned_data["ville"].strip()

    def clean_lieu_nom(self):
        return self.cleaned_data["lieu_nom"].strip()

    def clean_lieu_adresse(self):
        return self.cleaned_data["lieu_adresse"].strip()

    def clean_scene_details(self):
        return self.cleaned_data["scene_details"].strip()

    def clean_acces_logistique(self):
        return self.cleaned_data["acces_logistique"].strip()

    def clean_message(self):
        return self.cleaned_data["message"].strip()

    def clean(self):
        cleaned = super().clean()
        debut = cleaned.get("heure_debut")
        fin = cleaned.get("heure_fin")
        if debut and fin and fin <= debut:
            self.add_error(
                "heure_fin",
                "L’heure de fin doit être après l’heure de début.",
            )
        if cleaned.get("date_flexible") and not cleaned.get("date_alternative"):
            # Alternative optional even if flexible — no error
            pass
        return cleaned


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
        url_ext = cleaned.get("url_externe")
        ev_existant = cleaned.get("evenement_existant")
        ev_nouveau = cleaned.get("evenement_nouveau", "").strip()

        if not ev_existant and not ev_nouveau:
            raise forms.ValidationError("Choisissez un événement existant ou créez-en un nouveau.")

        if type_media == "photo":
            # Extension checks happen in the view for multi-upload; single file too.
            fichier = cleaned.get("fichier")
            if fichier:
                ext = "." + fichier.name.rsplit(".", 1)[-1].lower() if "." in fichier.name else ""
                if ext not in EXTENSIONS_AUTORISEES["photo"]:
                    raise forms.ValidationError(
                        f"Extension non autorisée. Acceptées : {', '.join(EXTENSIONS_AUTORISEES['photo'])}"
                    )
            return cleaned

        if type_media == "video" and not fichier and not url_ext:
            raise forms.ValidationError("Pour une vidéo, fournissez un fichier ou un lien externe.")

        if type_media not in ("photo", "video") and not fichier:
            raise forms.ValidationError("Veuillez sélectionner un fichier.")

        if fichier:
            if fichier.size > MAX_SIZE_BYTES:
                raise forms.ValidationError("Le fichier dépasse la limite de 1 Go.")
            ext = "." + fichier.name.rsplit(".", 1)[-1].lower() if "." in fichier.name else ""
            exts_ok = EXTENSIONS_AUTORISEES.get(type_media, [])
            if exts_ok and ext not in exts_ok:
                raise forms.ValidationError(f"Extension non autorisée. Acceptées : {', '.join(exts_ok)}")

        return cleaned

    def get_or_create_evenement(self):
        ev = self.cleaned_data.get("evenement_existant")
        if ev:
            return ev
        nom = self.cleaned_data.get("evenement_nouveau", "").strip()
        date = self.cleaned_data.get("evenement_date")
        ev, _ = EvenementMedia.objects.get_or_create(nom=nom, defaults={"date": date})
        return ev

from __future__ import annotations

import re
from urllib.parse import urlparse

from django import forms

from events.models import Event
from repertoire.models import Part, PartPoste, Piece, Setlist

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".ogg", ".oga", ".aac", ".flac", ".webm"}
_AUDIO_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/x-wav",
    "audio/ogg",
    "audio/aac",
    "audio/flac",
    "audio/webm",
}


def _validate_youtube_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        raise forms.ValidationError("Indiquez un lien YouTube valide.")
    if host in ("youtu.be", "www.youtu.be"):
        if not (parsed.path or "").strip("/"):
            raise forms.ValidationError("Lien YouTube incomplet.")
    elif "watch" in (parsed.path or "") or "/embed/" in (parsed.path or "") or "/shorts/" in (
        parsed.path or ""
    ):
        pass
    elif re.search(r"/[A-Za-z0-9_-]{6,}", parsed.path or ""):
        pass
    else:
        raise forms.ValidationError("Lien YouTube incomplet.")
    return value


class PieceForm(forms.ModelForm):
    class Meta:
        model = Piece
        fields = (
            "title",
            "is_published",
            "remarks",
            "chorus_order",
            "youtube_url_1",
            "youtube_url_2",
            "youtube_url_3",
            "audio_recording",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": "pl-input"}),
            "remarks": forms.Textarea(attrs={"class": "pl-input", "rows": 5}),
            "chorus_order": forms.HiddenInput(),
            "youtube_url_1": forms.URLInput(
                attrs={
                    "class": "pl-input",
                    "placeholder": "https://www.youtube.com/watch?v=…",
                    "inputmode": "url",
                }
            ),
            "youtube_url_2": forms.URLInput(
                attrs={
                    "class": "pl-input",
                    "placeholder": "https://youtu.be/…",
                    "inputmode": "url",
                }
            ),
            "youtube_url_3": forms.URLInput(
                attrs={
                    "class": "pl-input",
                    "placeholder": "https://www.youtube.com/watch?v=…",
                    "inputmode": "url",
                }
            ),
            "audio_recording": forms.ClearableFileInput(
                attrs={"accept": "audio/*,.mp3,.m4a,.wav,.ogg,.aac,.flac,.webm"}
            ),
        }

    def clean_youtube_url_1(self):
        return _validate_youtube_url(self.cleaned_data.get("youtube_url_1", ""))

    def clean_youtube_url_2(self):
        return _validate_youtube_url(self.cleaned_data.get("youtube_url_2", ""))

    def clean_youtube_url_3(self):
        return _validate_youtube_url(self.cleaned_data.get("youtube_url_3", ""))

    def clean_audio_recording(self):
        f = self.cleaned_data.get("audio_recording")
        if not f or not getattr(f, "name", None):
            return f
        # ClearableFileField can return False when clearing
        if f is False:
            return f
        name = (getattr(f, "name", "") or "").lower()
        ctype = (getattr(f, "content_type", "") or "").lower()
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        if ext not in _AUDIO_EXTS and ctype not in _AUDIO_TYPES and not ctype.startswith("audio/"):
            raise forms.ValidationError(
                "Fichier audio attendu (mp3, m4a, wav, ogg, aac, flac, webm)."
            )
        return f


class PartUploadForm(forms.Form):
    poste = forms.ChoiceField(
        label="Poste",
        choices=PartPoste.choices,
        widget=forms.Select(attrs={"class": "pl-input"}),
    )
    file = forms.FileField(
        label="PDF",
        widget=forms.ClearableFileInput(attrs={"accept": "application/pdf,.pdf"}),
    )
    source_name = forms.CharField(
        label="Nom source",
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "pl-input"}),
    )

    def clean_file(self):
        f = self.cleaned_data["file"]
        name = (getattr(f, "name", "") or "").lower()
        ctype = (getattr(f, "content_type", "") or "").lower()
        if not (name.endswith(".pdf") or ctype == "application/pdf"):
            raise forms.ValidationError("Le fichier doit être un PDF.")
        return f


class ImagesToPartForm(forms.Form):
    poste = forms.ChoiceField(
        label="Poste",
        choices=PartPoste.choices,
        widget=forms.Select(attrs={"class": "pl-input"}),
    )


class PdfSplitForm(forms.Form):
    source_pdf = forms.FileField(
        label="PDF multi-parties",
        widget=forms.ClearableFileInput(attrs={"accept": "application/pdf,.pdf"}),
    )
    poste = forms.ChoiceField(
        label="Poste cible",
        choices=PartPoste.choices,
        widget=forms.Select(attrs={"class": "pl-input"}),
    )
    page_start = forms.IntegerField(
        label="Page début",
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "pl-input"}),
    )
    page_end = forms.IntegerField(
        label="Page fin",
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "pl-input"}),
    )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("page_start")
        end = cleaned.get("page_end")
        if start and end and end < start:
            raise forms.ValidationError("La page de fin doit être ≥ page de début.")
        return cleaned


class SetlistForm(forms.ModelForm):
    class Meta:
        model = Setlist
        fields = ("title", "event", "notes", "is_active")
        widgets = {
            "title": forms.TextInput(attrs={"class": "pl-input"}),
            "event": forms.Select(attrs={"class": "pl-input"}),
            "notes": forms.Textarea(attrs={"class": "pl-input", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event"].queryset = Event.objects.order_by("-date_debut")
        self.fields["event"].required = False


class SetlistDuplicateForm(forms.Form):
    title = forms.CharField(
        label="Nouveau titre",
        max_length=200,
        widget=forms.TextInput(attrs={"class": "pl-input"}),
    )
    event = forms.ModelChoiceField(
        label="Événement cible",
        queryset=Event.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "pl-input"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["event"].queryset = Event.objects.order_by("-date_debut")

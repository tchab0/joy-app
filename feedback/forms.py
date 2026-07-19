from __future__ import annotations

from django import forms

from feedback.models import PageFeedback
from feedback.roles import VOTE_ROLE_LABELS


class PageFeedbackForm(forms.ModelForm):
    existing_feedback_id = forms.CharField(required=False, widget=forms.HiddenInput)
    importance = forms.IntegerField(required=False, min_value=0, max_value=5)

    class Meta:
        model = PageFeedback
        fields = ("category", "importance", "message", "page_url", "page_title", "page_context")
        widgets = {
            "category": forms.RadioSelect,
            "message": forms.Textarea(
                attrs={
                    "rows": 4,
                    "minlength": "10",
                    "maxlength": "2000",
                    "placeholder": "Décrivez le problème ou votre suggestion (10 caractères minimum)…",
                }
            ),
            "page_url": forms.HiddenInput(),
            "page_title": forms.HiddenInput(),
            "page_context": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices = PageFeedback.CATEGORY_CHOICES
        self.fields["message"].required = False

    def clean_existing_feedback_id(self):
        raw = (self.cleaned_data.get("existing_feedback_id") or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError as exc:
            raise forms.ValidationError("Retour invalide.") from exc

    def clean_importance(self):
        value = self.cleaned_data.get("importance")
        if value in (None, 0):
            return 1
        return value

    def clean(self):
        cleaned = super().clean()
        existing_id = cleaned.get("existing_feedback_id")
        message = (cleaned.get("message") or "").strip()
        if existing_id:
            from feedback.services.page_feedback import pending_page_feedback_queryset

            page_url = (cleaned.get("page_url") or "").strip()
            category = cleaned.get("category")
            exists = (
                pending_page_feedback_queryset(page_url=page_url, category=category)
                .filter(pk=existing_id)
                .exists()
            )
            if not exists:
                self.add_error(
                    "existing_feedback_id",
                    "Ce retour n'est plus disponible. Choisissez-en un autre ou rédigez une nouvelle description.",
                )
            cleaned["message"] = message
            return cleaned

        if len(message) < 10:
            self.add_error("message", "Le message doit contenir au moins 10 caractères.")
        elif len(message) > 2000:
            self.add_error("message", "Le message ne peut pas dépasser 2000 caractères.")
        cleaned["message"] = message
        return cleaned


class PageFeedbackVoteOpenForm(forms.Form):
    formulation = forms.CharField(
        label="Formulation soumise au vote",
        widget=forms.Textarea(attrs={"rows": 4, "minlength": "10", "maxlength": "2000"}),
    )
    vote_roles = forms.MultipleChoiceField(
        label="Rôles appelés à voter",
        required=True,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vote_roles"].choices = list(VOTE_ROLE_LABELS.items())

    def clean_formulation(self):
        formulation = (self.cleaned_data.get("formulation") or "").strip()
        if len(formulation) < 10:
            raise forms.ValidationError("La formulation doit contenir au moins 10 caractères.")
        if len(formulation) > 2000:
            raise forms.ValidationError("La formulation ne peut pas dépasser 2000 caractères.")
        return formulation

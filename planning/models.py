from django.conf import settings
from django.db import models
from django.utils import timezone


class ParticipationStatus(models.Model):
    code = models.SlugField(
        max_length=50,
        unique=True,
        verbose_name="Code",
        help_text="Clé technique stable (ex : invited, confirmed, declined)",
    )
    label = models.CharField(
        max_length=100,
        verbose_name="Libellé",
    )
    color_token = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Token couleur",
        help_text="Ex : success, warning, danger, neutral",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Ordre d’affichage",
    )
    is_active = models.BooleanField(default=True, verbose_name="Actif")

    class Meta:
        ordering = ["sort_order", "label"]
        verbose_name = "Statut de participation"
        verbose_name_plural = "Statuts de participation"

    def __str__(self):
        return self.label


class OrchestraSection(models.Model):
    """Pupitre / section de l’orchestre (sax altos, trompettes…)."""

    code = models.SlugField(max_length=50, unique=True, verbose_name="Code")
    name = models.CharField(max_length=100, verbose_name="Nom")
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="Ordre")
    is_active = models.BooleanField(default=True, verbose_name="Actif")

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Pupitre"
        verbose_name_plural = "Pupitres"

    def __str__(self):
        return self.name


class MusicianProfile(models.Model):
    class RosterStatus(models.TextChoices):
        TITULAIRE = "titulaire", "Titulaire"
        REMPLACANT = "remplacant", "Remplaçant"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="musician_profile",
        verbose_name="Utilisateur",
    )
    section = models.ForeignKey(
        OrchestraSection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="musicians",
        verbose_name="Pupitre",
    )
    instrument = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Instrument",
        help_text="Précision libre (ex. trompette 2, batterie).",
    )
    roster_status = models.CharField(
        max_length=20,
        choices=RosterStatus.choices,
        default=RosterStatus.TITULAIRE,
        verbose_name="Statut",
        help_text="Les titulaires sont convoqués à chaque nouvelle date ; "
        "les remplaçants sont sollicités uniquement en cas de besoin.",
    )

    class Meta:
        verbose_name = "Profil musicien"
        verbose_name_plural = "Profils musiciens"
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self):
        return f"{self.user} — {self.section or 'sans pupitre'}"

    @property
    def is_titulaire(self) -> bool:
        return self.roster_status == self.RosterStatus.TITULAIRE

    @property
    def is_remplacant(self) -> bool:
        return self.roster_status == self.RosterStatus.REMPLACANT


class EventParticipation(models.Model):
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="participations",
        verbose_name="Concert",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="event_participations",
        verbose_name="Musicien",
    )
    status = models.ForeignKey(
        "planning.ParticipationStatus",
        on_delete=models.PROTECT,
        related_name="participations",
        verbose_name="Statut",
    )
    comment = models.TextField(
        blank=True,
        verbose_name="Commentaire",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        ordering = ["event__date_debut", "user__last_name", "user__first_name"]
        verbose_name = "Participation concert"
        verbose_name_plural = "Participations concerts"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "user"],
                name="unique_event_participation_per_user",
            )
        ]

    def __str__(self):
        return f"{self.event} – {self.user}"


class DateProposal(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Ouvert"
        LOCKED = "locked", "Verrouillé"
        CANCELLED = "cancelled", "Annulé"

    title = models.CharField(max_length=200, verbose_name="Titre")
    description = models.TextField(blank=True, verbose_name="Description")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        verbose_name="Statut",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="date_proposals_created",
        verbose_name="Créé par",
    )
    locked_option = models.ForeignKey(
        "planning.DateOption",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Option retenue",
    )
    linked_event = models.ForeignKey(
        "events.Event",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="from_proposals",
        verbose_name="Événement lié",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Sondage de dates"
        verbose_name_plural = "Sondages de dates"

    def __str__(self):
        return self.title

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.OPEN


class DateOption(models.Model):
    proposal = models.ForeignKey(
        DateProposal,
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name="Sondage",
    )
    starts_at = models.DateTimeField(verbose_name="Début")
    ends_at = models.DateTimeField(null=True, blank=True, verbose_name="Fin")
    label = models.CharField(max_length=120, blank=True, verbose_name="Libellé")
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="Ordre")

    class Meta:
        ordering = ["sort_order", "starts_at"]
        verbose_name = "Option de date"
        verbose_name_plural = "Options de date"

    def __str__(self):
        if self.label:
            return self.label
        return timezone.localtime(self.starts_at).strftime("%d/%m/%Y %H:%M")


class DateVote(models.Model):
    class Choice(models.TextChoices):
        YES = "yes", "Oui"
        NO = "no", "Non"
        MAYBE = "maybe", "Peut-être"

    option = models.ForeignKey(
        DateOption,
        on_delete=models.CASCADE,
        related_name="votes",
        verbose_name="Option",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="date_votes",
        verbose_name="Musicien",
    )
    choice = models.CharField(
        max_length=10,
        choices=Choice.choices,
        verbose_name="Vote",
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Vote de date"
        verbose_name_plural = "Votes de date"
        constraints = [
            models.UniqueConstraint(
                fields=["option", "user"],
                name="unique_date_vote_per_option_user",
            )
        ]

    def __str__(self):
        return f"{self.user} → {self.option}: {self.choice}"


class SubstituteRequest(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposé"
        ACCEPTED = "accepted", "Accepté"
        DECLINED = "declined", "Refusé"
        CANCELLED = "cancelled", "Annulé"

    participation = models.ForeignKey(
        EventParticipation,
        on_delete=models.CASCADE,
        related_name="substitute_requests",
        verbose_name="Participation d’origine",
    )
    candidate = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="substitute_offers",
        verbose_name="Candidat remplaçant",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROPOSED,
        verbose_name="Statut",
    )
    note = models.CharField(max_length=255, blank=True, verbose_name="Note")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Demande de remplaçant"
        verbose_name_plural = "Demandes de remplaçants"
        constraints = [
            models.UniqueConstraint(
                fields=["participation", "candidate"],
                name="unique_substitute_per_participation_candidate",
            )
        ]

    def __str__(self):
        return f"{self.participation} → {self.candidate} ({self.status})"

    @property
    def event(self):
        return self.participation.event


class EquipmentItem(models.Model):
    name = models.CharField(max_length=120, verbose_name="Nom")
    category = models.CharField(max_length=80, blank=True, verbose_name="Catégorie")
    description = models.TextField(blank=True, verbose_name="Description")
    is_active = models.BooleanField(default=True, verbose_name="Actif")
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="Ordre")

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Matériel"
        verbose_name_plural = "Matériels"

    def __str__(self):
        return self.name


class EventEquipmentAssignment(models.Model):
    class Status(models.TextChoices):
        NEEDED = "needed", "À prévoir"
        OK = "ok", "OK"
        MISSING = "missing", "Manquant"

    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="equipment_assignments",
        verbose_name="Événement",
    )
    item = models.ForeignKey(
        EquipmentItem,
        on_delete=models.PROTECT,
        related_name="assignments",
        verbose_name="Matériel",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipment_assignments",
        verbose_name="Apporté par",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEEDED,
        verbose_name="Statut",
    )
    notes = models.CharField(max_length=255, blank=True, verbose_name="Notes")

    class Meta:
        ordering = ["item__sort_order", "item__name"]
        verbose_name = "Matériel d’événement"
        verbose_name_plural = "Matériels d’événement"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "item"],
                name="unique_equipment_per_event_item",
            )
        ]

    def __str__(self):
        return f"{self.event} — {self.item}"

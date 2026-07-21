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
    class Poste(models.TextChoices):
        """Chaises d’un big band standard (5 sax / 4 tp / 4 tb / rythmique)."""

        ALTO_1 = "alto_1", "1er alto"
        ALTO_2 = "alto_2", "2e alto"
        TENOR_1 = "tenor_1", "1er ténor"
        TENOR_2 = "tenor_2", "2e ténor"
        BARYTON = "baryton", "Sax baryton"
        TROMPETTE_1 = "trompette_1", "1er trompette"
        TROMPETTE_2 = "trompette_2", "2e trompette"
        TROMPETTE_3 = "trompette_3", "3e trompette"
        TROMPETTE_4 = "trompette_4", "4e trompette"
        TROMBONE_1 = "trombone_1", "1er trombone"
        TROMBONE_2 = "trombone_2", "2e trombone"
        TROMBONE_3 = "trombone_3", "3e trombone"
        TROMBONE_4 = "trombone_4", "4e trombone (basse)"
        PIANO = "piano", "Piano"
        GUITARE = "guitare", "Guitare"
        BASSE = "basse", "Basse"
        BATTERIE = "batterie", "Batterie"
        CLARINETTE = "clarinette", "Clarinette"
        CHANT = "chant", "Chant"
        PERCUSSION = "percussion", "Percussions"

    # Poste → code OrchestraSection (aligné sur seed_planning.DEFAULT_SECTIONS).
    POSTE_SECTION_CODE = {
        Poste.ALTO_1: "sax-alto",
        Poste.ALTO_2: "sax-alto",
        Poste.TENOR_1: "sax-tenor",
        Poste.TENOR_2: "sax-tenor",
        Poste.BARYTON: "sax-baryton",
        Poste.CLARINETTE: "clarinette",
        Poste.TROMPETTE_1: "trompette",
        Poste.TROMPETTE_2: "trompette",
        Poste.TROMPETTE_3: "trompette",
        Poste.TROMPETTE_4: "trompette",
        Poste.TROMBONE_1: "trombone",
        Poste.TROMBONE_2: "trombone",
        Poste.TROMBONE_3: "trombone",
        Poste.TROMBONE_4: "trombone",
        Poste.PIANO: "rythmique",
        Poste.GUITARE: "rythmique",
        Poste.BASSE: "rythmique",
        Poste.BATTERIE: "rythmique",
        Poste.PERCUSSION: "rythmique",
        Poste.CHANT: "chant",
    }

    SECTION_DEFAULTS = {
        "sax-alto": ("Saxophones altos", 10),
        "sax-tenor": ("Saxophones ténors", 20),
        "sax-baryton": ("Saxophone baryton", 30),
        "clarinette": ("Clarinette", 35),
        "trompette": ("Trompettes", 40),
        "trombone": ("Trombones", 50),
        "rythmique": ("Rythmique", 60),
        "chant": ("Chant", 70),
    }

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
        help_text="Déduit automatiquement du poste titulaire.",
    )
    poste_titulaire = models.CharField(
        max_length=30,
        blank=True,
        choices=Poste.choices,
        verbose_name="Poste titulaire",
        help_text="Chaise pour laquelle le musicien est titulaire "
        "(convoqué à chaque nouvelle date). Détermine le pupitre.",
    )
    # Jusqu’à 4 chaises de remplacement (poste_remplacant = 1er slot).
    MAX_POSTES_REMPLACANT = 4
    POSTE_REMPLACANT_FIELDS = (
        "poste_remplacant",
        "poste_remplacant_2",
        "poste_remplacant_3",
        "poste_remplacant_4",
    )

    poste_remplacant = models.CharField(
        max_length=30,
        blank=True,
        choices=Poste.choices,
        verbose_name="Poste remplaçant",
        help_text="1re chaise de remplacement. Laisser vide si non remplaçant.",
    )
    poste_remplacant_2 = models.CharField(
        max_length=30,
        blank=True,
        choices=Poste.choices,
        verbose_name="Poste remplaçant 2",
    )
    poste_remplacant_3 = models.CharField(
        max_length=30,
        blank=True,
        choices=Poste.choices,
        verbose_name="Poste remplaçant 3",
    )
    poste_remplacant_4 = models.CharField(
        max_length=30,
        blank=True,
        choices=Poste.choices,
        verbose_name="Poste remplaçant 4",
    )

    class Meta:
        verbose_name = "Profil musicien"
        verbose_name_plural = "Profils musiciens"
        ordering = ["user__last_name", "user__first_name"]

    def __str__(self):
        return f"{self.user} — {self.section or 'sans pupitre'}"

    @property
    def is_titulaire(self) -> bool:
        return bool(self.poste_titulaire)

    @property
    def is_remplacant(self) -> bool:
        return bool(self.postes_remplacant)

    @property
    def postes_remplacant(self) -> list[str]:
        """Postes de remplacement renseignés, sans doublon, ordre conservé."""
        seen: set[str] = set()
        out: list[str] = []
        for field in self.POSTE_REMPLACANT_FIELDS:
            value = getattr(self, field) or ""
            if value and value not in seen:
                seen.add(value)
                out.append(value)
        return out

    def set_postes_remplacant(self, postes: list[str]) -> None:
        """Normalise et écrit jusqu’à MAX_POSTES_REMPLACANT postes distincts."""
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in postes:
            value = (raw or "").strip()
            if not value or value not in self.Poste.values:
                continue
            if value in seen:
                continue
            seen.add(value)
            cleaned.append(value)
            if len(cleaned) >= self.MAX_POSTES_REMPLACANT:
                break
        for i, field in enumerate(self.POSTE_REMPLACANT_FIELDS):
            setattr(self, field, cleaned[i] if i < len(cleaned) else "")

    def get_poste_remplacant_label(self, poste: str) -> str:
        return dict(self.Poste.choices).get(poste, poste)

    @property
    def postes_remplacant_display(self) -> list[str]:
        return [self.get_poste_remplacant_label(p) for p in self.postes_remplacant]

    def roles_label(self) -> str:
        """Libellé compact des rôles (liste admin, roster)."""
        parts: list[str] = []
        if self.poste_titulaire:
            parts.append(f"{self.get_poste_titulaire_display()} (tit.)")
        for label in self.postes_remplacant_display:
            parts.append(f"{label} (remp.)")
        return " · ".join(parts) if parts else "—"

    @classmethod
    def section_for_poste(cls, poste: str, *, create: bool = False) -> OrchestraSection | None:
        """Résout le pupitre correspondant à un poste (création optionnelle)."""
        code = cls.POSTE_SECTION_CODE.get(poste or "")
        if not code:
            return None
        if create:
            name, order = cls.SECTION_DEFAULTS[code]
            section, _ = OrchestraSection.objects.get_or_create(
                code=code,
                defaults={"name": name, "sort_order": order, "is_active": True},
            )
            return section
        return OrchestraSection.objects.filter(code=code).first()

    def sync_section_from_poste(self) -> None:
        """Pupitre = pupitre du poste titulaire (source de vérité)."""
        self.section = self.section_for_poste(self.poste_titulaire, create=True)

    def save(self, *args, **kwargs):
        self.sync_section_from_poste()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"section"}
        super().save(*args, **kwargs)


class EventParticipation(models.Model):
    class RoleKind(models.TextChoices):
        TITULAIRE = "titulaire", "Titulaire"
        REMPLACANT = "remplacant", "Remplaçant"

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
    poste = models.CharField(
        max_length=30,
        blank=True,
        choices=MusicianProfile.Poste.choices,
        verbose_name="Poste convoqué",
        help_text="Chaise pour laquelle le musicien est convoqué à cette date.",
    )
    role_kind = models.CharField(
        max_length=20,
        blank=True,
        choices=RoleKind.choices,
        verbose_name="Rôle",
        help_text="Titulaire ou remplaçant pour ce poste.",
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
        indexes = [
            models.Index(fields=["event", "status"], name="plan_part_event_status_idx"),
            models.Index(fields=["user", "event"], name="plan_part_user_event_idx"),
        ]

    def __str__(self):
        return f"{self.event} – {self.user}"

    @property
    def poste_label(self) -> str:
        """Libellé du poste convoqué (ex. « Sax baryton (tit.) »)."""
        if not self.poste:
            return "—"
        label = self.get_poste_display()
        if self.role_kind == self.RoleKind.TITULAIRE:
            return f"{label} (tit.)"
        if self.role_kind == self.RoleKind.REMPLACANT:
            return f"{label} (remp.)"
        return label

    def section_for_roster(self) -> OrchestraSection | None:
        """Pupitre d’affichage = pupitre du poste convoqué, sinon profil."""
        if self.poste:
            return MusicianProfile.section_for_poste(self.poste)
        try:
            return self.user.musician_profile.section
        except MusicianProfile.DoesNotExist:
            return None


class DateProposal(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon (en attente staff)"
        OPEN = "open", "Ouvert"
        LOCKED = "locked", "Verrouillé"
        CANCELLED = "cancelled", "Annulé"

    title = models.CharField(max_length=200, verbose_name="Titre")
    description = models.TextField(blank=True, verbose_name="Description")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
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
    launched_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Lancé le",
        help_text="Date à laquelle le staff a ouvert le sondage aux musiciens.",
    )
    launched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="date_proposals_launched",
        verbose_name="Lancé par",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Sondage de dates"
        verbose_name_plural = "Sondages de dates"
        indexes = [
            models.Index(fields=["status"], name="plan_proposal_status_idx"),
        ]

    def __str__(self):
        return self.title

    @property
    def is_draft(self) -> bool:
        return self.status == self.Status.DRAFT

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

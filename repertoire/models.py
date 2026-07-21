from __future__ import annotations

import re
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from planning.models import MusicianProfile

_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")


def extract_youtube_id(url: str) -> str | None:
    """Extrait l’id vidéo d’une URL YouTube (watch, youtu.be, embed, shorts)."""
    if not url:
        return None
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").strip("/")

    if host in ("youtu.be", "www.youtu.be"):
        candidate = path.split("/")[0] if path else ""
    else:
        qs = parse_qs(parsed.query)
        if qs.get("v"):
            candidate = qs["v"][0]
        else:
            m = re.search(r"(?:embed|shorts|live)/([A-Za-z0-9_-]{6,})", parsed.path or "")
            candidate = m.group(1) if m else ""

    if candidate and _YOUTUBE_ID_RE.match(candidate):
        return candidate
    return None


def part_upload_to(instance: "Part", filename: str) -> str:
    ext = Path(filename or "").suffix.lower()[:16] or ".pdf"
    if ext != ".pdf":
        ext = ".pdf"
    return f"repertoire/parts/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


def piece_audio_upload_to(instance: "Piece", filename: str) -> str:
    ext = Path(filename or "").suffix.lower()[:16]
    if ext not in {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac"}:
        ext = ".mp3"
    return f"repertoire/audio/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


class Piece(models.Model):
    title = models.CharField("Titre", max_length=200)
    slug = models.SlugField("Slug", max_length=220, unique=True)
    is_published = models.BooleanField(
        "Publié",
        default=False,
        help_text="Visible par les musiciens une fois publié.",
    )
    remarks = models.TextField(
        "Remarques",
        blank=True,
        help_text="Intro, structure, comment commencer…",
    )
    chorus_order = models.TextField(
        "Ordre des chorus",
        blank=True,
        help_text="Dernière décision d’ordre des solos.",
    )
    chorus_order_updated_at = models.DateTimeField(
        "Chorus mis à jour le",
        null=True,
        blank=True,
    )
    youtube_url_1 = models.URLField(
        "Lien YouTube 1",
        max_length=500,
        blank=True,
        help_text="Vidéo de référence (optionnel).",
    )
    youtube_url_2 = models.URLField(
        "Lien YouTube 2",
        max_length=500,
        blank=True,
    )
    youtube_url_3 = models.URLField(
        "Lien YouTube 3",
        max_length=500,
        blank=True,
    )
    audio_recording = models.FileField(
        "Enregistrement audio",
        upload_to=piece_audio_upload_to,
        blank=True,
        help_text="Version propre du morceau (mp3, m4a, wav, ogg…).",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ["title"]
        verbose_name = "morceau"
        verbose_name_plural = "morceaux"

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "morceau"
            candidate = base
            n = 2
            while Piece.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{n}"
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def update_chorus_order(self, text: str) -> None:
        self.chorus_order = (text or "").strip()
        self.chorus_order_updated_at = timezone.now()
        self.save(update_fields=["chorus_order", "chorus_order_updated_at", "updated_at"])

    def youtube_links(self) -> list[str]:
        return [
            url
            for url in (self.youtube_url_1, self.youtube_url_2, self.youtube_url_3)
            if url
        ]

    def youtube_videos(self) -> list[dict[str, str]]:
        """Liens YouTube enrichis (id, vignette, embed) pour l’affichage."""
        videos: list[dict[str, str]] = []
        for i, url in enumerate(self.youtube_links(), start=1):
            vid = extract_youtube_id(url)
            if not vid:
                continue
            videos.append(
                {
                    "url": url,
                    "id": vid,
                    "label": f"Vidéo {i}",
                    "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                    "embed": f"https://www.youtube-nocookie.com/embed/{vid}?rel=0",
                }
            )
        return videos


class PartPoste(models.TextChoices):
    """Postes planning + conducteur / autre pour les partitions."""

    ALTO_1 = MusicianProfile.Poste.ALTO_1.value, MusicianProfile.Poste.ALTO_1.label
    ALTO_2 = MusicianProfile.Poste.ALTO_2.value, MusicianProfile.Poste.ALTO_2.label
    TENOR_1 = MusicianProfile.Poste.TENOR_1.value, MusicianProfile.Poste.TENOR_1.label
    TENOR_2 = MusicianProfile.Poste.TENOR_2.value, MusicianProfile.Poste.TENOR_2.label
    BARYTON = MusicianProfile.Poste.BARYTON.value, MusicianProfile.Poste.BARYTON.label
    TROMPETTE_1 = (
        MusicianProfile.Poste.TROMPETTE_1.value,
        MusicianProfile.Poste.TROMPETTE_1.label,
    )
    TROMPETTE_2 = (
        MusicianProfile.Poste.TROMPETTE_2.value,
        MusicianProfile.Poste.TROMPETTE_2.label,
    )
    TROMPETTE_3 = (
        MusicianProfile.Poste.TROMPETTE_3.value,
        MusicianProfile.Poste.TROMPETTE_3.label,
    )
    TROMPETTE_4 = (
        MusicianProfile.Poste.TROMPETTE_4.value,
        MusicianProfile.Poste.TROMPETTE_4.label,
    )
    TROMBONE_1 = (
        MusicianProfile.Poste.TROMBONE_1.value,
        MusicianProfile.Poste.TROMBONE_1.label,
    )
    TROMBONE_2 = (
        MusicianProfile.Poste.TROMBONE_2.value,
        MusicianProfile.Poste.TROMBONE_2.label,
    )
    TROMBONE_3 = (
        MusicianProfile.Poste.TROMBONE_3.value,
        MusicianProfile.Poste.TROMBONE_3.label,
    )
    TROMBONE_4 = (
        MusicianProfile.Poste.TROMBONE_4.value,
        MusicianProfile.Poste.TROMBONE_4.label,
    )
    PIANO = MusicianProfile.Poste.PIANO.value, MusicianProfile.Poste.PIANO.label
    GUITARE = MusicianProfile.Poste.GUITARE.value, MusicianProfile.Poste.GUITARE.label
    BASSE = MusicianProfile.Poste.BASSE.value, MusicianProfile.Poste.BASSE.label
    BATTERIE = MusicianProfile.Poste.BATTERIE.value, MusicianProfile.Poste.BATTERIE.label
    CLARINETTE = (
        MusicianProfile.Poste.CLARINETTE.value,
        MusicianProfile.Poste.CLARINETTE.label,
    )
    CHANT = MusicianProfile.Poste.CHANT.value, MusicianProfile.Poste.CHANT.label
    PERCUSSION = (
        MusicianProfile.Poste.PERCUSSION.value,
        MusicianProfile.Poste.PERCUSSION.label,
    )
    CONDUCTEUR = "conducteur", "Conducteur"
    AUTRE = "autre", "Autre"


class Part(models.Model):
    piece = models.ForeignKey(
        Piece,
        on_delete=models.CASCADE,
        related_name="parts",
        verbose_name="Morceau",
    )
    poste = models.CharField(
        "Poste",
        max_length=30,
        choices=PartPoste.choices,
        db_index=True,
    )
    file = models.FileField("Fichier PDF", upload_to=part_upload_to)
    source_name = models.CharField("Nom source", max_length=255, blank=True)
    sort_order = models.PositiveSmallIntegerField("Ordre", default=0)
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifié le", auto_now=True)

    class Meta:
        ordering = ["sort_order", "poste"]
        verbose_name = "partition"
        verbose_name_plural = "partitions"
        constraints = [
            models.UniqueConstraint(
                fields=["piece", "poste"],
                name="unique_part_per_piece_poste",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.piece.title} — {self.get_poste_display()}"


class Setlist(models.Model):
    title = models.CharField("Titre", max_length=200)
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="setlists",
        verbose_name="Événement",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_setlists",
        verbose_name="Créée par",
    )
    notes = models.TextField("Notes", blank=True)
    is_active = models.BooleanField(
        "Active",
        default=True,
        help_text="Si liée à un événement, seule la setlist active est affichée.",
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    updated_at = models.DateTimeField("Modifiée le", auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "setlist"
        verbose_name_plural = "setlists"

    def __str__(self) -> str:
        return self.title

    def duplicate(self, *, title: str | None = None, event=None, created_by=None) -> "Setlist":
        new = Setlist.objects.create(
            title=title or f"{self.title} (copie)",
            event=event,
            created_by=created_by or self.created_by,
            notes=self.notes,
            is_active=True,
        )
        items = [
            SetlistItem(
                setlist=new,
                piece_id=item.piece_id,
                position=item.position,
                note=item.note,
            )
            for item in self.items.select_related("piece").order_by("position")
        ]
        SetlistItem.objects.bulk_create(items)
        return new

    def sync_items(
        self,
        ordered_piece_ids: list[int],
        notes_by_piece: dict[int, str] | None = None,
    ) -> None:
        """Remplace l’ordre des morceaux (positions 1..n). Les notes sont optionnelles."""
        notes_by_piece = notes_by_piece or {}
        # Déduplique en conservant le premier ordre demandé
        seen: set[int] = set()
        unique_ids: list[int] = []
        for pid in ordered_piece_ids:
            if pid in seen:
                continue
            seen.add(pid)
            unique_ids.append(pid)

        valid_ids = set(
            Piece.objects.filter(pk__in=unique_ids).values_list("pk", flat=True)
        )
        unique_ids = [pid for pid in unique_ids if pid in valid_ids]

        existing = {item.piece_id: item for item in self.items.all()}
        for position, piece_id in enumerate(unique_ids, start=1):
            note = (notes_by_piece.get(piece_id) or "").strip()[:200]
            if piece_id in existing:
                item = existing.pop(piece_id)
                if item.position != position or item.note != note:
                    item.position = position
                    item.note = note
                    item.save(update_fields=["position", "note"])
            else:
                SetlistItem.objects.create(
                    setlist=self,
                    piece_id=piece_id,
                    position=position,
                    note=note,
                )
        for item in existing.values():
            item.delete()


class SetlistItem(models.Model):
    setlist = models.ForeignKey(
        Setlist,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Setlist",
    )
    piece = models.ForeignKey(
        Piece,
        on_delete=models.CASCADE,
        related_name="setlist_items",
        verbose_name="Morceau",
    )
    position = models.PositiveSmallIntegerField("Position", default=0)
    note = models.CharField("Note", max_length=200, blank=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "élément de setlist"
        verbose_name_plural = "éléments de setlist"
        constraints = [
            models.UniqueConstraint(
                fields=["setlist", "piece"],
                name="unique_piece_per_setlist",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.position}. {self.piece.title}"

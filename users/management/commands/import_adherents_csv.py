"""Fusionne un export d’adhésions HelloAsso avec les comptes utilisateurs.

Le CSV HelloAsso fait foi pour l’identité (nom, prénom, e-mail, téléphone).
Les comptes déjà connectés ne sont jamais réinitialisés : seuls les champs
vides sont complétés. Les comptes qui ne se sont **jamais** connectés reçoivent
l’identifiant ``prenom.nom``, un mot de passe provisoire et le drapeau
``must_change_password``.

    python manage.py import_adherents_csv chemin/export.csv --dry-run
    python manage.py import_adherents_csv chemin/export.csv
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_date

from planning.models import MusicianProfile
from planning.services import get_or_create_profile
from users.phone import normalize_phone
from users.roles import sync_user_groups

User = get_user_model()

DEFAULT_PASSWORD = "Joy-joy-joy"

# Statuts de commande HelloAsso à importer (normalisés sans accent).
ACCEPTED_STATUSES = frozenset({"valide", "authorized", "registered"})

# Inversions nom / prénom saisies par l’adhérent côté HelloAsso, clé = e-mail.
NAME_FIXES: dict[str, tuple[str, str]] = {
    "tmbussy@hotmail.com": ("Thierry", "Bussy"),
    "petitchloe@hotmail.com": ("Chloé", "Petit-Brun"),
    "francineheulin@yahoo.fr": ("Raphaël", "Ravon"),
}

Poste = MusicianProfile.Poste

# « Instrument joué » (texte libre) → chaise, uniquement quand la chaise est
# sans ambiguïté. Un « saxophone » ou « trompette » nu reste à affecter par le
# staff : le numéro de pupitre n’est pas déductible.
_POSTE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("sax bar", Poste.BARYTON),
    ("saxo bar", Poste.BARYTON),
    ("baryton", Poste.BARYTON),
    ("bariton", Poste.BARYTON),
    ("tenor 2", Poste.TENOR_2),
    ("tenor 1", Poste.TENOR_1),
    ("alto 2", Poste.ALTO_2),
    ("alto 1", Poste.ALTO_1),
    ("trompette 1", Poste.TROMPETTE_1),
    ("trompette 2", Poste.TROMPETTE_2),
    ("trompette 3", Poste.TROMPETTE_3),
    ("trompette 4", Poste.TROMPETTE_4),
    ("trombone 1", Poste.TROMBONE_1),
    ("trombone 2", Poste.TROMBONE_2),
    ("trombone 3", Poste.TROMBONE_3),
    ("trombone 4", Poste.TROMBONE_4),
    ("batterie", Poste.BATTERIE),
    ("drums", Poste.BATTERIE),
    ("percussion", Poste.PERCUSSION),
    ("contrebasse", Poste.BASSE),
    ("basse", Poste.BASSE),
    ("guitare", Poste.GUITARE),
    ("guitar", Poste.GUITARE),
    ("piano", Poste.PIANO),
    ("clavier", Poste.PIANO),
    ("clarinette", Poste.CLARINETTE),
    ("clarinet", Poste.CLARINETTE),
    ("chant", Poste.CHANT),
    ("chanteu", Poste.CHANT),
    ("voix", Poste.CHANT),
    ("vocal", Poste.CHANT),
)


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return decomposed.encode("ascii", "ignore").decode("ascii")


def _norm_header(value: str) -> str:
    """« Prénom adhérent » → ``prenomadherent`` (comparaison robuste)."""
    return re.sub(r"[^a-z0-9]+", "", _strip_accents(value or "").lower())


def _norm_text(value: str) -> str:
    """Texte libre → minuscules sans accent ni emoji, espaces normalisés."""
    cleaned = re.sub(r"[^a-z0-9]+", " ", _strip_accents(value or "").lower())
    return " ".join(cleaned.split())


def _name_key(*parts: str) -> frozenset[str]:
    """Clé d’identité insensible à l’ordre, à la casse et aux accents."""
    tokens = _norm_text(" ".join(parts)).split()
    return frozenset(tokens)


def _fix_case(value: str) -> str:
    """« MENGIN » / « anita » → « Mengin » / « Anita ». Casse mixte préservée."""
    cleaned = " ".join((value or "").split())
    if not cleaned:
        return ""
    if cleaned == cleaned.upper() or cleaned == cleaned.lower():
        return cleaned.title()
    return cleaned


def _slug_username(first: str, last: str) -> str:
    base = _strip_accents(f"{first} {last}").lower()
    base = re.sub(r"[^a-z0-9]+", ".", base).strip(".")
    return base[:40] or "musicien"


def _parse_order_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _poste_for_instrument(instrument: str) -> str:
    text = _norm_text(instrument)
    if not text:
        return ""
    for needle, poste in _POSTE_PATTERNS:
        if needle in text:
            return poste
    return ""


@dataclass
class Adherent:
    first_name: str
    last_name: str
    email: str
    phone: str
    instrument: str
    order_date: date | None


@dataclass
class Outcome:
    label: str
    username: str
    name: str
    notes: list[str] = field(default_factory=list)


class Command(BaseCommand):
    help = (
        "Fusionne un export CSV d’adhésions HelloAsso avec les comptes "
        "existants et prépare les identifiants des comptes jamais connectés."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_path",
            type=Path,
            help="Chemin du CSV HelloAsso (séparateur « ; »).",
        )
        parser.add_argument(
            "--password",
            default=DEFAULT_PASSWORD,
            help=f"Mot de passe provisoire (défaut : {DEFAULT_PASSWORD}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche le rapport sans rien écrire en base.",
        )
        parser.add_argument(
            "--skip-other-pending",
            action="store_true",
            help=(
                "N’applique l’identifiant / mot de passe provisoire qu’aux "
                "personnes du CSV, sans toucher aux autres comptes jamais "
                "connectés."
            ),
        )
        parser.add_argument(
            "--include-staff",
            action="store_true",
            help="Réinitialise aussi les comptes staff / superuser jamais connectés.",
        )
        parser.add_argument(
            "--membership-expires",
            default="",
            help=(
                "Date de fin d’adhésion (AAAA-MM-JJ) à poser sur les personnes "
                "du CSV. Sans valeur, les flags d’adhésion ne sont pas touchés."
            ),
        )
        parser.add_argument(
            "--no-poste",
            action="store_true",
            help="N’essaie pas de déduire la chaise depuis « Instrument joué ».",
        )

    def handle(self, *args, **options):
        csv_path: Path = options["csv_path"]
        if not csv_path.is_file():
            raise CommandError(f"CSV introuvable : {csv_path}")

        password: str = options["password"]
        dry_run: bool = options["dry_run"]

        expires_raw: str = (options["membership_expires"] or "").strip()
        membership_expires: date | None = None
        if expires_raw:
            membership_expires = parse_date(expires_raw)
            if membership_expires is None:
                raise CommandError(
                    f"--membership-expires attend AAAA-MM-JJ, reçu : {expires_raw!r}"
                )

        adherents, skipped = self._read_csv(csv_path)
        if not adherents:
            raise CommandError("Aucune adhésion exploitable dans le CSV.")

        self.outcomes: list[Outcome] = []
        self.warnings: list[str] = []
        self.handled_pks: set[int] = set()
        self.pending_count = 0

        with transaction.atomic():
            self._names = self._name_index()
            for adherent in adherents:
                self._merge_adherent(
                    adherent,
                    password=password,
                    membership_expires=membership_expires,
                    include_staff=options["include_staff"],
                    assign_poste=not options["no_poste"],
                )
            if not options["skip_other_pending"]:
                self._reset_other_pending(
                    password=password,
                    include_staff=options["include_staff"],
                    handled=self.handled_pks,
                )
            if dry_run:
                transaction.set_rollback(True)

        self._report(adherents, skipped, dry_run=dry_run, password=password)

    # — Lecture CSV ————————————————————————————————————————————————

    def _read_csv(self, path: Path) -> tuple[list[Adherent], list[str]]:
        skipped: list[str] = []
        by_email: dict[str, Adherent] = {}
        anonymous: list[Adherent] = []

        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh, delimiter=";")
            try:
                header = next(reader)
            except StopIteration:
                raise CommandError("CSV vide.")

            cols = {_norm_header(name): idx for idx, name in enumerate(header)}
            required = ("nomadherent", "prenomadherent")
            missing = [c for c in required if c not in cols]
            if missing:
                raise CommandError(
                    "Colonnes manquantes dans le CSV : " + ", ".join(missing)
                )

            def cell(row: list[str], key: str) -> str:
                idx = cols.get(key)
                if idx is None or idx >= len(row):
                    return ""
                return (row[idx] or "").strip()

            for row in reader:
                if not any((value or "").strip() for value in row):
                    continue

                status = _norm_text(cell(row, "statutdelacommande"))
                last_name = _fix_case(cell(row, "nomadherent"))
                first_name = _fix_case(cell(row, "prenomadherent"))
                email = (
                    cell(row, "email") or cell(row, "emailpayeur")
                ).strip().lower()

                if status and status not in ACCEPTED_STATUSES:
                    skipped.append(
                        f"{first_name} {last_name} — commande « "
                        f"{cell(row, 'statutdelacommande')} »"
                    )
                    continue
                if not (first_name or last_name):
                    skipped.append("ligne sans nom ni prénom")
                    continue

                if email in NAME_FIXES:
                    first_name, last_name = NAME_FIXES[email]

                adherent = Adherent(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=normalize_phone(cell(row, "telephone")),
                    instrument=cell(row, "instrumentjoue"),
                    order_date=_parse_order_date(cell(row, "datedelacommande")),
                )

                if not email:
                    anonymous.append(adherent)
                    continue

                previous = by_email.get(email)
                if previous is None:
                    by_email[email] = adherent
                    continue
                # Doublon d’adhésion : on garde la commande la plus récente.
                if (adherent.order_date or date.min) >= (
                    previous.order_date or date.min
                ):
                    by_email[email] = adherent

        adherents = sorted(
            [*by_email.values(), *anonymous],
            key=lambda a: (a.last_name.lower(), a.first_name.lower()),
        )
        return adherents, skipped

    # — Fusion ————————————————————————————————————————————————————

    def _name_index(self) -> dict[frozenset[str], User]:
        index: dict[frozenset[str], User] = {}
        for user in User.objects.all():
            key = _name_key(user.first_name, user.last_name)
            if key and key not in index:
                index[key] = user
        return index

    def _find_user(self, adherent: Adherent) -> tuple[User | None, str]:
        if adherent.email:
            user = User.objects.filter(email__iexact=adherent.email).first()
            if user is not None:
                return user, "e-mail"
        key = _name_key(adherent.first_name, adherent.last_name)
        if key:
            user = self._names.get(key)
            if user is not None:
                return user, "nom"
        return None, ""

    def _merge_adherent(
        self,
        adherent: Adherent,
        *,
        password: str,
        membership_expires: date | None,
        include_staff: bool,
        assign_poste: bool,
    ) -> None:
        user, matched_by = self._find_user(adherent)
        notes: list[str] = []
        created = user is None

        if created:
            user = User(
                username=self._free_username(
                    adherent.first_name, adherent.last_name, None
                ),
                email=adherent.email,
                first_name=adherent.first_name,
                last_name=adherent.last_name,
                phone=adherent.phone,
                is_musician=True,
                is_active=True,
            )
            user.set_unusable_password()
            user.save()
        else:
            notes.append(f"rapproché par {matched_by}")
            self._merge_identity(user, adherent, notes)

        if membership_expires is not None:
            user.is_association_member = True
            user.membership_expires_at = membership_expires

        user.is_musician = True
        self._apply_pending_credentials(
            user,
            adherent.first_name,
            adherent.last_name,
            password,
            include_staff,
            notes,
        )
        user.save()
        sync_user_groups(user)

        if assign_poste:
            self._assign_poste(user, adherent, notes)

        self.handled_pks.add(user.pk)
        self._names[_name_key(user.first_name, user.last_name)] = user
        self.outcomes.append(
            Outcome(
                label="créé" if created else "fusionné",
                username=user.username,
                name=user.get_full_name() or user.username,
                notes=notes,
            )
        )

    def _merge_identity(
        self, user: User, adherent: Adherent, notes: list[str]
    ) -> None:
        """Complète les champs vides ; signale les divergences sans écraser."""
        same_person = _name_key(user.first_name, user.last_name) == _name_key(
            adherent.first_name, adherent.last_name
        )
        for attr, value in (
            ("first_name", adherent.first_name),
            ("last_name", adherent.last_name),
        ):
            current = getattr(user, attr)
            if not value or current == value:
                continue
            if not current or same_person:
                # Même personne : le CSV corrige la casse ou l’inversion.
                setattr(user, attr, value)
            else:
                notes.append(f"{attr} en base « {current} » ≠ CSV « {value} »")

        if adherent.email and not user.email:
            user.email = adherent.email
        elif adherent.email and user.email.lower() != adherent.email:
            notes.append(f"e-mail en base « {user.email} » ≠ CSV « {adherent.email} »")

        if adherent.phone and not user.phone:
            user.phone = adherent.phone
        elif adherent.phone and normalize_phone(user.phone) != adherent.phone:
            notes.append("téléphone différent du CSV (base conservée)")

    def _free_username(self, first: str, last: str, user: User | None) -> str:
        """``prenom.nom``, suffixé si un autre compte l’occupe déjà."""
        base = _slug_username(first, last)

        def taken(name: str) -> bool:
            qs = User.objects.filter(username=name)
            if user is not None:
                qs = qs.exclude(pk=user.pk)
            return qs.exists()

        if not taken(base):
            return base
        suffix = 2
        while taken(f"{base}.{suffix}"):
            suffix += 1
        return f"{base}.{suffix}"

    def _apply_pending_credentials(
        self,
        user: User,
        first_name: str,
        last_name: str,
        password: str,
        include_staff: bool,
        notes: list[str],
    ) -> None:
        """Identifiant ``prenom.nom`` + mot de passe provisoire, jamais connecté."""
        if user.last_login is not None:
            notes.append("déjà connecté : identifiant et mot de passe intacts")
            return
        if (user.is_staff or user.is_superuser) and not include_staff:
            notes.append("compte staff : mot de passe non touché")
            return

        base = _slug_username(first_name, last_name)
        desired = self._free_username(first_name, last_name, user)
        if desired != user.username:
            if desired != base:
                notes.append(f"identifiant « {base} » déjà pris → « {desired} »")
            user.username = desired

        user.set_password(password)
        user.must_change_password = True
        self.pending_count += 1

    def _assign_poste(
        self, user: User, adherent: Adherent, notes: list[str]
    ) -> None:
        instrument = (adherent.instrument or "").strip()
        if not instrument:
            return
        profile = get_or_create_profile(user)
        if profile.poste_titulaire:
            return

        poste = _poste_for_instrument(instrument)
        if not poste:
            notes.append(f"chaise à affecter (« {instrument} »)")
            return
        taken = (
            MusicianProfile.objects.filter(poste_titulaire=poste)
            .exclude(pk=profile.pk)
            .exists()
        )
        if taken:
            notes.append(
                f"chaise à affecter (« {instrument} » → "
                f"{poste} déjà occupée)"
            )
            return
        profile.poste_titulaire = poste
        profile.save()
        notes.append(f"chaise {profile.get_poste_titulaire_display()}")

    def _reset_other_pending(
        self, *, password: str, include_staff: bool, handled: set[int]
    ) -> None:
        """Comptes absents du CSV et jamais connectés : mêmes règles d’accès."""
        qs = User.objects.filter(last_login__isnull=True, is_active=True).exclude(
            pk__in=handled
        )
        if not include_staff:
            qs = qs.exclude(is_staff=True).exclude(is_superuser=True)

        for user in qs.order_by("last_name", "first_name", "username"):
            if not (user.first_name or user.last_name):
                self.warnings.append(
                    f"« {user.username} » sans nom ni prénom : identifiant inchangé"
                )
                continue
            notes: list[str] = ["hors CSV"]
            self._apply_pending_credentials(
                user,
                user.first_name,
                user.last_name,
                password,
                include_staff,
                notes,
            )
            user.save()
            self.outcomes.append(
                Outcome(
                    label="accès",
                    username=user.username,
                    name=user.get_full_name() or user.username,
                    notes=notes,
                )
            )

    # — Rapport ————————————————————————————————————————————————————

    def _report(
        self,
        adherents: list[Adherent],
        skipped: list[str],
        *,
        dry_run: bool,
        password: str,
    ) -> None:
        write = self.stdout.write
        if dry_run:
            write(self.style.WARNING("*** DRY-RUN : aucune écriture en base ***"))

        write(f"Adhésions retenues dans le CSV : {len(adherents)}")
        if skipped:
            write(f"Lignes ignorées : {len(skipped)}")
            for line in skipped:
                write(f"  - {line}")

        width = max((len(o.username) for o in self.outcomes), default=8)
        for label, title in (
            ("créé", "Comptes créés"),
            ("fusionné", "Comptes fusionnés"),
            ("accès", "Comptes hors CSV jamais connectés"),
        ):
            rows = [o for o in self.outcomes if o.label == label]
            if not rows:
                continue
            write("")
            write(self.style.MIGRATE_HEADING(f"{title} ({len(rows)})"))
            for outcome in rows:
                write(f"  {outcome.username:<{width}}  {outcome.name}")
                for note in outcome.notes:
                    write(f"  {'':<{width}}  · {note}")

        if self.warnings:
            write("")
            write(self.style.WARNING("À vérifier"))
            for line in self.warnings:
                write(f"  - {line}")

        write("")
        write(
            self.style.SUCCESS(
                f"{self.pending_count} compte(s) avec mot de passe provisoire "
                f"« {password} » — changement imposé à la première connexion."
            )
        )

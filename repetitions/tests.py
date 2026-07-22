from django.test import TestCase
from django.utils import timezone

from events.models import Event, EventType, Venue
from planning import services as planning_services
from planning.models import EventParticipation, MusicianProfile
from planning.services import ensure_participation_statuses
from repertoire.models import Piece
from repetitions.forms import RehearsalCreateForm
from repetitions.models import RehearsalPlan
from repetitions.services import (
    DEFAULT_REHEARSAL_VENUE_NOM,
    DEFAULT_REHEARSAL_VENUE_VILLE,
    confirm_titulaires_to_rehearsal,
    create_rehearsal,
    resolve_rehearsal_venue,
    set_rehearsal_absence,
)
from users.models import User


class RehearsalServicesTests(TestCase):
    def setUp(self):
        planning_services._STATUS_CACHE = None
        ensure_participation_statuses(force=True)
        self.venue = Venue.objects.create(nom="Salle", ville="La Roche")
        self.staff = User.objects.create_user(
            username="staff", password="x", is_staff=True
        )
        self.tit = User.objects.create_user(
            username="tit", password="x", is_musician=True
        )
        MusicianProfile.objects.update_or_create(
            user=self.tit,
            defaults={"poste_titulaire": MusicianProfile.Poste.ALTO_1},
        )
        self.piece = Piece.objects.create(title="Blue Train", is_published=True)

    def test_create_rehearsal_confirms_titulaires(self):
        event, plan = create_rehearsal(
            titre="Répé mardi",
            venue=self.venue,
            date_debut=timezone.now() + timezone.timedelta(days=3),
            created_by=self.staff,
            piece_ids=[self.piece.pk],
        )
        self.assertTrue(event.is_rehearsal)
        self.assertEqual(plan.items.count(), 1)
        part = EventParticipation.objects.get(event=event, user=self.tit)
        self.assertEqual(part.status.code, "confirmed")

    def test_absence_toggle(self):
        event, _ = create_rehearsal(
            titre="Répé",
            venue=self.venue,
            date_debut=timezone.now() + timezone.timedelta(days=2),
        )
        part = EventParticipation.objects.get(event=event, user=self.tit)
        set_rehearsal_absence(part, absent=True)
        part.refresh_from_db()
        self.assertEqual(part.status.code, "declined")
        set_rehearsal_absence(part, absent=False)
        part.refresh_from_db()
        self.assertEqual(part.status.code, "confirmed")

    def test_confirm_titulaires_idempotent(self):
        et = EventType.objects.create(nom="Répétition")
        event = Event(
            titre="Existante",
            type=et,
            venue=self.venue,
            date_debut=timezone.now() + timezone.timedelta(days=5),
            statut=Event.Statut.CONFIRME,
        )
        event._skip_titulaire_invite = True
        event.save()
        n1 = confirm_titulaires_to_rehearsal(event)
        n2 = confirm_titulaires_to_rehearsal(event)
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 0)
        RehearsalPlan.objects.create(event=event)
        self.assertTrue(hasattr(event, "rehearsal_plan"))

    def test_resolve_default_rehearsal_venue(self):
        before = Venue.objects.count()
        venue = resolve_rehearsal_venue(mode="default")
        self.assertEqual(venue.nom, DEFAULT_REHEARSAL_VENUE_NOM)
        self.assertEqual(venue.ville, DEFAULT_REHEARSAL_VENUE_VILLE)
        again = resolve_rehearsal_venue(mode="default")
        self.assertEqual(again.pk, venue.pk)
        self.assertEqual(Venue.objects.count(), before + 1)

    def test_resolve_custom_rehearsal_venue(self):
        venue = resolve_rehearsal_venue(
            mode="custom",
            nom="Salle des fêtes",
            ville="Aizenay",
            adresse="1 rue Test",
        )
        self.assertEqual(venue.nom, "Salle des fêtes")
        self.assertEqual(venue.ville, "Aizenay")
        again = resolve_rehearsal_venue(
            mode="custom", nom="Salle des fêtes", ville="Aizenay"
        )
        self.assertEqual(again.pk, venue.pk)

    def test_create_form_defaults_to_mingus_mode(self):
        form = RehearsalCreateForm(
            data={
                "titre": "Répé",
                "date": "2026-08-01",
                "time_start": "20:00",
                "venue_mode": "default",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["venue_mode"], "default")

    def test_create_form_custom_requires_nom_ville(self):
        form = RehearsalCreateForm(
            data={
                "titre": "Répé",
                "date": "2026-08-01",
                "time_start": "20:00",
                "venue_mode": "custom",
                "venue_nom": "",
                "venue_ville": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("venue_nom", form.errors)
        self.assertIn("venue_ville", form.errors)

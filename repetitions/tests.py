from django.test import TestCase
from django.utils import timezone

from events.models import Event, EventType, Venue
from planning import services as planning_services
from planning.models import EventParticipation, MusicianProfile
from planning.services import ensure_participation_statuses
from repertoire.models import Piece
from repetitions.models import RehearsalPlan
from repetitions.services import (
    confirm_titulaires_to_rehearsal,
    create_rehearsal,
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

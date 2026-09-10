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
        planning_services._constants._STATUS_CACHE = None
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
        self.assertEqual(part.comment, "Absent à la répétition")
        set_rehearsal_absence(part, absent=False)
        part.refresh_from_db()
        self.assertEqual(part.status.code, "confirmed")
        self.assertEqual(part.comment, "")
        set_rehearsal_absence(part, absent=True, comment="Contrôle médical")
        part.refresh_from_db()
        self.assertEqual(part.comment, "Contrôle médical")

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

    def test_create_form_notify_musicians_opt_in(self):
        unbound = RehearsalCreateForm()
        self.assertFalse(unbound.fields["notify_musicians"].initial)
        form = RehearsalCreateForm(
            data={
                "titre": "Répé",
                "date": "2026-08-01",
                "time_start": "20:00",
                "venue_mode": "default",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.cleaned_data["notify_musicians"])

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

    def test_attach_calendar_rehearsal_plans(self):
        from planning.services import attach_calendar_rehearsal_plans

        event, _ = create_rehearsal(
            titre="Répé setlist",
            venue=self.venue,
            date_debut=timezone.now() + timezone.timedelta(days=4),
            created_by=self.staff,
            piece_ids=[self.piece.pk],
        )
        empty, _ = create_rehearsal(
            titre="Répé vide",
            venue=self.venue,
            date_debut=timezone.now() + timezone.timedelta(days=5),
            created_by=self.staff,
        )
        concert_type = EventType.objects.create(nom="Concert", is_rehearsal=False)
        concert = Event.objects.create(
            titre="Concert",
            type=concert_type,
            venue=self.venue,
            date_debut=timezone.now() + timezone.timedelta(days=6),
        )
        attach_calendar_rehearsal_plans([event, empty, concert])
        self.assertEqual(event.cal_rehearsal_plan["n_items"], 1)
        self.assertEqual(empty.cal_rehearsal_plan["n_items"], 0)
        self.assertIsNone(concert.cal_rehearsal_plan)

    def test_notify_rehearsal_mentions_setlist_salon(self):
        from users.models import UserNotification
        from repetitions.services import notify_rehearsal_created

        event, _ = create_rehearsal(
            titre="Répé notif",
            venue=self.venue,
            date_debut=timezone.now() + timezone.timedelta(days=7),
            created_by=self.staff,
        )
        notify_rehearsal_created(event, [self.tit])
        notif = UserNotification.objects.filter(user=self.tit).latest("created_at")
        self.assertIn("proposez des morceaux", notif.body.lower())
        self.assertIn("👍", notif.body)

    def test_create_rehearsal_no_notification_by_default(self):
        from chat.models import ChatMembership, ChatMessage, ChatRoom
        from chat.services import REHEARSAL_SETLIST_TIP_PREFIX
        from users.models import UserNotification

        before = UserNotification.objects.filter(user=self.tit).count()
        event, _ = create_rehearsal(
            titre="Répé silencieuse",
            venue=self.venue,
            date_debut=timezone.now() + timezone.timedelta(days=8),
            created_by=self.staff,
        )
        self.assertEqual(
            UserNotification.objects.filter(user=self.tit).count(), before
        )
        room = ChatRoom.objects.get(event=event)
        tip = ChatMessage.objects.get(
            room=room,
            kind=ChatMessage.Kind.SYSTEM,
            body__startswith=REHEARSAL_SETLIST_TIP_PREFIX,
        )
        membership = ChatMembership.objects.get(room=room, user=self.tit)
        self.assertGreaterEqual(membership.last_digested_message_id, tip.pk)

    def test_create_rehearsal_notifies_when_requested(self):
        from users.models import UserNotification

        before = UserNotification.objects.filter(user=self.tit).count()
        create_rehearsal(
            titre="Répé annoncée",
            venue=self.venue,
            date_debut=timezone.now() + timezone.timedelta(days=9),
            created_by=self.staff,
            notify_musicians=True,
        )
        self.assertEqual(
            UserNotification.objects.filter(user=self.tit).count(), before + 1
        )
        notif = UserNotification.objects.filter(user=self.tit).latest("created_at")
        self.assertEqual(notif.title, "JOY — Répétition")

    def test_repetitions_detail_page_lead_known(self):
        from users.page_leads import KNOWN_PAGE_LEAD_KEYS, dismiss_page_lead

        self.assertIn("repetitions.detail", KNOWN_PAGE_LEAD_KEYS)
        self.assertTrue(dismiss_page_lead(self.tit, "repetitions.detail"))
        self.assertIn("repetitions.detail", self.tit.dismissed_page_leads)

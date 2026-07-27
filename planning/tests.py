from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from chat.models import ChatRoom
from chat.services import post_message
from events.models import Event, EventType, Organisme, Venue
from planning.models import (
    DateProposal,
    EquipmentItem,
    EventEquipmentAssignment,
    EventParticipation,
    MusicianProfile,
    OrchestraSection,
    SubstituteRequest,
)
from planning.services import (
    attach_roster_substitutes,
    calendar_chat_links_for_user,
    calendar_summaries_for_events,
    ensure_participation_statuses,
    invite_slots_for_profile,
    propose_substitute,
    remplacants_for_poste,
    respond_substitute_request,
    roster_by_stage,
    set_participation_response,
)
from planning import services as planning_services

User = get_user_model()


class PlanningBaseTestCase(TestCase):
    def setUp(self):
        planning_services._constants._STATUS_CACHE = None
        self.statuses = ensure_participation_statuses(force=True)
        self.section = OrchestraSection.objects.create(
            code="trompette", name="Trompettes", sort_order=10
        )
        self.venue = Venue.objects.create(nom="Salle Test", ville="La Roche-sur-Yon")
        self.event_type = EventType.objects.create(nom="Répétition", is_rehearsal=True)
        self.musician = User.objects.create_user(
            username="musi",
            password="pass12345",
            is_musician=True,
            first_name="Ada",
            last_name="Lovelace",
        )
        self.sub = User.objects.create_user(
            username="sub1",
            password="pass12345",
            is_musician=True,
            first_name="Remy",
            last_name="Placant",
        )
        # Profil auto-créé par signal ensure_musician_profile
        profile = self.musician.musician_profile
        profile.section = self.section
        profile.poste_titulaire = MusicianProfile.Poste.TROMPETTE_1
        profile.save()
        sub_profile = self.sub.musician_profile
        sub_profile.section = self.section
        sub_profile.poste_remplacant = MusicianProfile.Poste.TROMPETTE_2
        sub_profile.save()
        self.staff = User.objects.create_user(
            username="staff1",
            password="pass12345",
            is_staff=True,
            is_musician=True,
        )
        self.event = Event.objects.create(
            titre="Répète vendredi",
            type=self.event_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=7),
            statut=Event.Statut.CONFIRME,
            public=False,
        )
        # Invitation individuelle (plus de convocation auto à la création).
        from planning.services import invite_musician_to_event

        self.participation, _ = invite_musician_to_event(
            self.event, self.musician, send_notification=False
        )
        self.client = Client()


class DashboardTests(PlanningBaseTestCase):
    def test_dashboard_requires_musician(self):
        outsider = User.objects.create_user(username="out", password="pass12345")
        self.client.login(username="out", password="pass12345")
        r = self.client.get(reverse("planning:dashboard"))
        self.assertIn(r.status_code, (302, 403))

    def test_year_calendar_is_default_planning(self):
        self.client.login(username="musi", password="pass12345")
        today = timezone.localdate()
        r = self.client.get(reverse("planning:dashboard"), {"year": today.year})
        self.assertEqual(r.status_code, 200)
        months = r.context["months"]
        self.assertEqual(len(months), 12)
        self.assertEqual(months[0]["number"], today.month)
        self.assertEqual(months[0]["year"], today.year)
        # 12ᵉ mois = mois courant − 1 de l’année suivante (juil. → juin+1).
        end_month = today.month - 1 if today.month > 1 else 12
        end_year = today.year + 1 if today.month > 1 else today.year
        self.assertEqual(months[-1]["number"], end_month)
        self.assertEqual(months[-1]["year"], end_year)
        self.assertEqual(r.context["start_month"], today.month)
        self.assertContains(r, "Répète vendredi")

    def test_rolling_calendar_shifted_year(self):
        self.client.login(username="musi", password="pass12345")
        today = timezone.localdate()
        year = today.year + 1
        r = self.client.get(reverse("planning:dashboard"), {"year": year})
        self.assertEqual(r.status_code, 200)
        months = r.context["months"]
        self.assertEqual(months[0]["number"], today.month)
        self.assertEqual(months[0]["year"], year)

    def test_my_board_ok(self):
        self.client.login(username="musi", password="pass12345")
        r = self.client.get(reverse("planning:my_board"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Répète vendredi")

    def test_staff_can_create_event_from_day(self):
        self.client.login(username="staff1", password="pass12345")
        day = (timezone.localdate() + timedelta(days=14)).isoformat()
        r = self.client.post(
            reverse("planning:create_event"),
            {
                "titre": "Nouveau concert",
                "date": day,
                "time": "19:30",
                "venue_mode": "existing",
                "venue_id": self.venue.pk,
                "type_id": self.event_type.pk,
            },
        )
        self.assertEqual(r.status_code, 302)
        event = Event.objects.get(titre="Nouveau concert")
        # Salon staff-only : pas de convocation auto.
        self.assertFalse(
            EventParticipation.objects.filter(
                event=event, user=self.musician
            ).exists()
        )
        draft = DateProposal.objects.filter(
            linked_event=event, status=DateProposal.Status.DRAFT
        )
        self.assertTrue(draft.exists())
        from chat.models import ChatMembership, ChatRoom

        room = ChatRoom.objects.get(event=event)
        self.assertTrue(
            ChatMembership.objects.filter(
                room=room, user=self.staff, left_at__isnull=True
            ).exists()
        )

    def test_staff_can_create_event_with_new_venue_and_parent(self):
        self.client.login(username="staff1", password="pass12345")
        day = (timezone.localdate() + timedelta(days=21)).isoformat()
        before_venues = Venue.objects.count()
        before_events = Event.objects.count()
        r = self.client.post(
            reverse("planning:create_event"),
            {
                "titre": "Concert festival",
                "date": day,
                "time": "20:00",
                "venue_mode": "new",
                "venue_nom": "Place Napoléon",
                "venue_ville": "La Roche-sur-Yon",
                "venue_adresse": "Place Napoléon",
                "parent_mode": "new",
                "parent_titre": "Festival d’été JOY",
                "type_id": self.event_type.pk,
            },
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Venue.objects.count(), before_venues + 1)
        # Parent + date créée
        self.assertEqual(Event.objects.count(), before_events + 2)
        venue = Venue.objects.get(nom="Place Napoléon")
        parent = Event.objects.get(titre="Festival d’été JOY")
        event = Event.objects.get(titre="Concert festival")
        self.assertEqual(event.venue_id, venue.pk)
        self.assertEqual(event.parent_id, parent.pk)
        self.assertEqual(parent.venue_id, venue.pk)
        # Le parent (conteneur) ne convoque pas les titulaires
        self.assertFalse(
            EventParticipation.objects.filter(event=parent).exists()
        )
        # La date créée non plus (salon staff-only).
        self.assertFalse(
            EventParticipation.objects.filter(event=event).exists()
        )

    def test_new_venue_saves_map_coordinates(self):
        self.client.login(username="staff1", password="pass12345")
        day = (timezone.localdate() + timedelta(days=22)).isoformat()
        r = self.client.post(
            reverse("planning:create_event"),
            {
                "titre": "Concert avec carte",
                "date": day,
                "time": "20:00",
                "venue_mode": "new",
                "venue_nom": "Théâtre municipal",
                "venue_ville": "La Roche-sur-Yon",
                "venue_adresse": "Place du Théâtre",
                "venue_latitude": "46.670123",
                "venue_longitude": "-1.426789",
                "type_id": self.event_type.pk,
                "organisme": "Ville de La Roche-sur-Yon",
            },
        )
        self.assertEqual(r.status_code, 302)
        venue = Venue.objects.get(nom="Théâtre municipal")
        self.assertEqual(str(venue.latitude), "46.670123")
        self.assertEqual(str(venue.longitude), "-1.426789")
        event = Event.objects.get(titre="Concert avec carte")
        self.assertEqual(event.organisme, "Ville de La Roche-sur-Yon")
        self.assertTrue(
            Organisme.objects.filter(nom="Ville de La Roche-sur-Yon").exists()
        )

    def test_existing_venue_can_update_coordinates(self):
        self.client.login(username="staff1", password="pass12345")
        day = (timezone.localdate() + timedelta(days=23)).isoformat()
        r = self.client.post(
            reverse("planning:create_event"),
            {
                "titre": "Maj coords",
                "date": day,
                "time": "21:00",
                "venue_mode": "existing",
                "venue_id": self.venue.pk,
                "venue_latitude": "46.671000",
                "venue_longitude": "-1.427000",
                "type_id": self.event_type.pk,
            },
        )
        self.assertEqual(r.status_code, 302)
        self.venue.refresh_from_db()
        self.assertEqual(str(self.venue.latitude), "46.671000")
        self.assertEqual(str(self.venue.longitude), "-1.427000")


class RespondTests(PlanningBaseTestCase):
    def test_respond_yes(self):
        self.client.login(username="musi", password="pass12345")
        r = self.client.post(
            reverse("planning:respond", args=[self.participation.pk]),
            data='{"response":"yes"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"]["code"], "confirmed")
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.status.code, "confirmed")

    def test_respond_maybe(self):
        set_participation_response(self.participation, "maybe")
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.status.code, "maybe")
        self.assertTrue(self.participation.maybe_remind_weekly)
        self.assertIsNotNone(self.participation.maybe_remind_at)

    def test_respond_maybe_with_date(self):
        event_day = timezone.localtime(self.event.date_debut).date()
        remind = timezone.localdate() + timedelta(days=2)
        if remind > event_day:
            remind = event_day
        set_participation_response(
            self.participation,
            "maybe",
            maybe_remind_at=remind.isoformat(),
            maybe_remind_weekly=False,
        )
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.status.code, "maybe")
        self.assertEqual(self.participation.maybe_remind_at, remind)
        self.assertTrue(self.participation.maybe_remind_weekly)

    def test_respond_maybe_weekly_via_api(self):
        self.client.login(username="musi", password="pass12345")
        r = self.client.post(
            reverse("planning:respond", args=[self.participation.pk]),
            data='{"response":"maybe","maybe_remind_weekly":true}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"]["code"], "maybe")
        self.assertTrue(data["maybe_remind"]["weekly"])
        self.participation.refresh_from_db()
        self.assertTrue(self.participation.maybe_remind_weekly)

    def test_yes_clears_maybe_remind(self):
        set_participation_response(
            self.participation, "maybe", maybe_remind_weekly=True
        )
        set_participation_response(self.participation, "yes")
        self.participation.refresh_from_db()
        self.assertIsNone(self.participation.maybe_remind_at)
        self.assertFalse(self.participation.maybe_remind_weekly)

    def test_confirmed_cannot_become_maybe(self):
        set_participation_response(self.participation, "yes")
        with self.assertRaises(ValueError):
            set_participation_response(self.participation, "maybe")
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.status.code, "confirmed")

    def test_api_confirmed_cannot_become_maybe(self):
        set_participation_response(self.participation, "yes")
        self.client.login(username="musi", password="pass12345")
        r = self.client.post(
            reverse("planning:respond", args=[self.participation.pk]),
            data='{"response":"maybe"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json().get("ok", True))
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.status.code, "confirmed")

    @patch("planning.services.rsvp.notify_users")
    def test_invalidate_confirmed_without_comment_notifies_staff(self, mock_notify):
        mock_notify.return_value = 1
        set_participation_response(self.participation, "yes")
        self.client.login(username="musi", password="pass12345")
        r = self.client.post(
            reverse("planning:respond", args=[self.participation.pk]),
            data='{"response":"no"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.status.code, "declined")
        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        self.assertIn("Présence annulée", kwargs["title"])
        self.assertIn("déjà confirmé", kwargs["body"])
        staff_ids = {u.pk for u in mock_notify.call_args.args[0]}
        self.assertIn(self.staff.pk, staff_ids)

    @patch("planning.services.rsvp.notify_users")
    def test_invalidate_confirmed_with_comment_notifies_staff(self, mock_notify):
        mock_notify.return_value = 1
        set_participation_response(self.participation, "yes")
        self.client.login(username="musi", password="pass12345")
        r = self.client.post(
            reverse("planning:respond", args=[self.participation.pk]),
            data='{"response":"no","comment":"Empêchement familial"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.status.code, "declined")
        self.assertEqual(self.participation.comment, "Empêchement familial")
        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        self.assertIn("Présence annulée", kwargs["title"])
        self.assertIn("Empêchement familial", kwargs["body"])
        self.assertIn("déjà confirmé", kwargs["body"])
        staff_ids = {u.pk for u in mock_notify.call_args.args[0]}
        self.assertIn(self.staff.pk, staff_ids)

    def test_decline_from_invited_without_comment_ok(self):
        self.client.login(username="musi", password="pass12345")
        r = self.client.post(
            reverse("planning:respond", args=[self.participation.pk]),
            data='{"response":"no"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.status.code, "declined")


class PollTests(PlanningBaseTestCase):
    def test_create_and_vote_and_lock(self):
        self.client.login(username="staff1", password="pass12345")
        starts = (timezone.now() + timedelta(days=14)).strftime("%Y-%m-%dT20:00")
        r = self.client.post(
            reverse("planning:create_poll"),
            {
                "title": "Choix date mars",
                "description": "Test",
                "deadline": (timezone.localdate() + timedelta(days=7)).isoformat(),
                "option_starts_0": starts,
                "option_label_0": "Vendredi",
            },
        )
        self.assertEqual(r.status_code, 302)
        proposal = DateProposal.objects.get(title="Choix date mars")
        self.assertEqual(proposal.status, DateProposal.Status.DRAFT)
        self.assertEqual(
            proposal.deadline, timezone.localdate() + timedelta(days=7)
        )
        option = proposal.options.get()

        # Lancement staff requis avant vote.
        r = self.client.post(reverse("planning:launch_poll", args=[proposal.pk]))
        self.assertEqual(r.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, DateProposal.Status.OPEN)

        # Poll sans événement lié : accès staff uniquement (CreatePollView).
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:vote_option", args=[option.pk]),
            data='{"choice":"yes"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["counts"]["yes"], 1)

        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:lock_poll", args=[proposal.pk]),
            {
                "option_id": option.pk,
                "venue_mode": "existing",
                "venue_id": self.venue.pk,
                "type_id": self.event_type.pk,
            },
        )
        self.assertEqual(r.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, DateProposal.Status.LOCKED)
        self.assertIsNotNone(proposal.linked_event)
        event = proposal.linked_event
        self.assertEqual(event.statut, Event.Statut.CONFIRME)
        # Verrouillage ne convoque plus automatiquement.
        self.assertFalse(
            EventParticipation.objects.filter(
                event=event, user=self.musician
            ).exists()
        )

    def test_poll_detail_shows_confirm_form_for_standalone_poll(self):
        from planning.models import DateOption
        from planning.services import launch_availability_poll

        proposal = DateProposal.objects.create(
            title="sondage test",
            status=DateProposal.Status.DRAFT,
            created_by=self.staff,
        )
        DateOption.objects.create(
            proposal=proposal,
            starts_at=timezone.now() + timedelta(days=7),
            label="Matinale",
        )
        launch_availability_poll(proposal, launched_by=self.staff)

        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:poll_detail", args=[proposal.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Confirmer l’événement")
        self.assertContains(r, "n’a pas encore d’événement")
        self.assertContains(r, 'name="type_id"')
        self.assertContains(r, 'name="venue_id"')

    def test_lock_linked_event_validates_date(self):
        """Sondage lié à un événement : option_id seul, pas de 2e Event."""
        from planning.models import DateOption
        from planning.services import launch_availability_poll

        starts = timezone.now() + timedelta(days=30)
        proposal = DateProposal.objects.create(
            title="Dispo répète",
            status=DateProposal.Status.DRAFT,
            linked_event=self.event,
            created_by=self.staff,
        )
        option = DateOption.objects.create(
            proposal=proposal,
            starts_at=starts,
            ends_at=starts + timedelta(hours=2),
            label="Option A",
        )
        launch_availability_poll(proposal, launched_by=self.staff)
        before_count = Event.objects.count()

        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:lock_poll", args=[proposal.pk]),
            {"option_id": option.pk},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Event.objects.count(), before_count)
        proposal.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(proposal.status, DateProposal.Status.LOCKED)
        self.assertEqual(proposal.locked_option_id, option.pk)
        self.assertEqual(proposal.linked_event_id, self.event.pk)
        self.assertEqual(self.event.date_debut, starts)
        self.assertEqual(self.event.statut, Event.Statut.CONFIRME)

    def test_poll_detail_embeds_salon_for_member(self):
        from planning.models import DateOption
        from planning.services import launch_availability_poll

        proposal = DateProposal.objects.create(
            title="Salon embed",
            status=DateProposal.Status.DRAFT,
            linked_event=self.event,
            created_by=self.staff,
        )
        DateOption.objects.create(
            proposal=proposal,
            starts_at=timezone.now() + timedelta(days=10),
            label="Date 1",
        )
        launch_availability_poll(proposal, launched_by=self.staff)

        self.client.login(username="musi", password="pass12345")
        r = self.client.get(reverse("planning:poll_detail", args=[proposal.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f"Salon « {self.event.titre} »")
        self.assertContains(r, "chat-room--embedded")
        self.assertContains(r, "Oui")
        # Plus de lien-only vers le salon.
        self.assertNotContains(r, 'class="pl-day-events__salon"')
        # Boutons dupliqués (haut + bas) quand salon présent.
        html = r.content.decode()
        self.assertEqual(html.count("@click=\"vote("), 6)  # 3 choices × 2 sections
        self.assertIn('aria-label="Dates proposées (bas de page)"', html)
        self.assertContains(r, "Oui 0 · Non 0 · Peut-être 0")
        self.assertContains(r, "pl-option__counts")

    def test_poll_detail_shows_vote_counts_for_musician(self):
        from planning.models import DateOption, DateVote
        from planning.services import cast_date_vote, launch_availability_poll

        proposal = DateProposal.objects.create(
            title="Totaux visibles",
            status=DateProposal.Status.DRAFT,
            linked_event=self.event,
            created_by=self.staff,
        )
        option = DateOption.objects.create(
            proposal=proposal,
            starts_at=timezone.now() + timedelta(days=11),
            label="Date A",
        )
        launch_availability_poll(proposal, launched_by=self.staff)
        cast_date_vote(option, self.musician, DateVote.Choice.YES)
        cast_date_vote(option, self.staff, DateVote.Choice.MAYBE)

        self.client.login(username="musi", password="pass12345")
        r = self.client.get(reverse("planning:poll_detail", args=[proposal.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Oui 1 · Non 0 · Peut-être 1")

    def test_poll_detail_shows_confirm_cta_for_staff(self):
        from planning.models import DateOption
        from planning.services import launch_availability_poll

        self.event.statut = Event.Statut.TENTATIVE
        self.event.save(update_fields=["statut"])
        proposal = DateProposal.objects.create(
            title="À confirmer",
            status=DateProposal.Status.DRAFT,
            linked_event=self.event,
            created_by=self.staff,
        )
        DateOption.objects.create(
            proposal=proposal,
            starts_at=timezone.now() + timedelta(days=14),
            label="Samedi",
        )
        launch_availability_poll(proposal, launched_by=self.staff)

        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:poll_detail", args=[proposal.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Confirmer l’événement")
        self.assertContains(r, reverse("planning:lock_poll", args=[proposal.pk]))
        # Musicien : pas le CTA staff
        self.client.login(username="musi", password="pass12345")
        r2 = self.client.get(reverse("planning:poll_detail", args=[proposal.pk]))
        self.assertEqual(r2.status_code, 200)
        self.assertNotContains(r2, "Après le sondage, retenez une date")

    def test_roster_shows_confirm_cta_for_open_poll(self):
        from planning.models import DateOption
        from planning.services import launch_availability_poll

        self.event.statut = Event.Statut.TENTATIVE
        self.event.save(update_fields=["statut"])
        proposal = DateProposal.objects.create(
            title="Roster confirm",
            status=DateProposal.Status.DRAFT,
            linked_event=self.event,
            created_by=self.staff,
        )
        DateOption.objects.create(
            proposal=proposal,
            starts_at=timezone.now() + timedelta(days=15),
        )
        launch_availability_poll(proposal, launched_by=self.staff)

        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:event_roster", args=[self.event.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Sondage ouvert — confirmer")
        self.assertContains(r, "Confirmer l’événement")

    def test_launch_poll_redirects_to_poll_detail(self):
        from planning.models import DateOption

        proposal = DateProposal.objects.create(
            title="Redirect poll",
            status=DateProposal.Status.DRAFT,
            linked_event=self.event,
            created_by=self.staff,
        )
        DateOption.objects.create(
            proposal=proposal,
            starts_at=timezone.now() + timedelta(days=12),
        )
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(reverse("planning:launch_poll", args=[proposal.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("planning:poll_detail", args=[proposal.pk]))


class OpenPollCalendarAndPendingTests(PlanningBaseTestCase):
    """Sondages lancés → propositions calendrier + CTA pending global."""

    def _make_open_poll(self, *day_offsets, title="Dispo mars"):
        from planning.models import DateOption
        from planning.services import launch_availability_poll

        proposal = DateProposal.objects.create(
            title=title,
            status=DateProposal.Status.DRAFT,
            linked_event=self.event,
            created_by=self.staff,
        )
        options = []
        for i, days in enumerate(day_offsets):
            options.append(
                DateOption.objects.create(
                    proposal=proposal,
                    starts_at=timezone.now() + timedelta(days=days),
                    label=f"Option {i + 1}",
                    sort_order=i,
                )
            )
        launch_availability_poll(proposal, launched_by=self.staff)
        proposal.refresh_from_db()
        return proposal, options

    def test_launched_poll_options_appear_as_calendar_proposals(self):
        from datetime import datetime as dt_cls, time as time_cls

        from planning.services import open_poll_calendar_markers_for_user

        # Dates distinctes de l’événement lié (répétition confirmée).
        proposal, options = self._make_open_poll(40, 47, title="Choix date bal")
        opt_day = timezone.localtime(options[0].starts_at).date()

        tz = timezone.get_current_timezone()
        range_start = timezone.make_aware(
            dt_cls.combine(opt_day.replace(day=1), time_cls.min), tz
        )
        range_end = timezone.now() + timedelta(days=120)

        markers = open_poll_calendar_markers_for_user(
            self.musician, range_start=range_start, range_end=range_end
        )
        self.assertEqual(len(markers), 2)
        self.assertTrue(all(m.cal_summary["is_proposal"] for m in markers))
        self.assertTrue(all(m.cal_summary["is_poll_option"] for m in markers))
        self.assertEqual({m.proposal_id for m in markers}, {proposal.pk})

        self.client.login(username="musi", password="pass12345")
        today = timezone.localdate()
        if opt_day.month >= today.month:
            window_year = opt_day.year
        else:
            window_year = opt_day.year - 1
        r = self.client.get(reverse("planning:dashboard"), {"year": window_year})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "has-proposal")
        self.assertContains(r, "Choix date bal")
        self.assertContains(r, "Proposition")

        # Musicien non invité : pas de marqueurs.
        other = User.objects.create_user(
            username="other_musi", password="pass12345", is_musician=True
        )
        markers_other = open_poll_calendar_markers_for_user(
            other, range_start=range_start, range_end=range_end
        )
        self.assertEqual(markers_other, [])

    def test_pending_polls_for_invited_musician_until_fully_voted(self):
        from planning.models import DateVote
        from planning.services import cast_date_vote, pending_polls_for_user

        proposal, options = self._make_open_poll(15, 22, title="Sondage pending")
        pending = pending_polls_for_user(self.musician)
        self.assertEqual([p.pk for p in pending], [proposal.pk])

        # Musicien non concerné
        other = User.objects.create_user(
            username="stranger", password="pass12345", is_musician=True
        )
        self.assertEqual(pending_polls_for_user(other), [])

        # Vote partiel → encore pending
        cast_date_vote(options[0], self.musician, DateVote.Choice.YES)
        self.assertEqual(
            [p.pk for p in pending_polls_for_user(self.musician)], [proposal.pk]
        )

        # Vote complet → plus pending
        cast_date_vote(options[1], self.musician, DateVote.Choice.NO)
        self.assertEqual(pending_polls_for_user(self.musician), [])

        # Calendrier / mes dates : banner global avec boutons de vote
        self.client.login(username="musi", password="pass12345")
        proposal2, options2 = self._make_open_poll(30, 33, title="Encore un sondage")
        r = self.client.get(reverse("planning:my_board"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "pl-poll-banner")
        self.assertContains(r, "Encore un sondage")
        self.assertContains(r, "Sondage")
        self.assertContains(r, "@click=\"vote(")
        self.assertContains(r, reverse("planning:vote_option", args=[options2[0].pk]))

        r2 = self.client.get(reverse("planning:dashboard"))
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, "pl-poll-banner")
        self.assertContains(r2, "Encore un sondage")
        self.assertContains(r2, "Oui")
        self.assertContains(r2, "Peut-être")
        self.assertContains(r2, "Non")

        # Page sondage : pas de banner (vote déjà sur la page)
        r3 = self.client.get(reverse("planning:poll_detail", args=[proposal2.pk]))
        self.assertEqual(r3.status_code, 200)
        self.assertNotContains(r3, "pl-poll-banner")

    def test_calendar_shows_recorded_vote_on_poll_marker(self):
        from datetime import datetime as dt_cls, time as time_cls

        from planning.models import DateVote
        from planning.services import cast_date_vote, open_poll_calendar_markers_for_user

        proposal, options = self._make_open_poll(40, title="Vote visible cal")
        cast_date_vote(options[0], self.musician, DateVote.Choice.YES)
        opt_day = timezone.localtime(options[0].starts_at).date()
        tz = timezone.get_current_timezone()
        markers = open_poll_calendar_markers_for_user(
            self.musician,
            range_start=timezone.make_aware(
                dt_cls.combine(opt_day.replace(day=1), time_cls.min), tz
            ),
            range_end=timezone.now() + timedelta(days=120),
        )
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].cal_summary["my_poll_vote"], "yes")
        self.assertEqual(markers[0].cal_summary["my_poll_vote_label"], "Oui")
        self.assertTrue(markers[0].cal_summary["poll_answered"])
        self.assertEqual(
            markers[0].cal_summary["poll_vote_counts"],
            {"yes": 1, "no": 0, "maybe": 0},
        )
        self.assertEqual(
            markers[0].cal_summary["poll_vote_counts_label"],
            "Oui 1 · Non 0 · Peut-être 0",
        )

        self.client.login(username="musi", password="pass12345")
        today = timezone.localdate()
        window_year = opt_day.year if opt_day.month >= today.month else opt_day.year - 1
        r = self.client.get(
            reverse("planning:dashboard"),
            {"year": window_year, "day": opt_day.isoformat()},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Votre réponse : Oui")
        self.assertContains(r, "Votre vote est enregistré")
        self.assertContains(r, "Oui 1 · Non 0 · Peut-être 0")
        self.assertNotContains(r, "Sondage ouvert — votez pour cette date")

    def test_same_day_tentative_event_shows_poll_vote_status(self):
        """Événement tentative même jour : marqueur omis, carte Event enrichie."""
        from planning.models import DateOption, DateVote
        from planning.services import (
            attach_calendar_summaries,
            attach_open_poll_info_to_events,
            cast_date_vote,
            launch_availability_poll,
        )

        concert_type = EventType.objects.create(nom="Concert")
        starts = timezone.now() + timedelta(days=35)
        event = Event.objects.create(
            titre="Bal d’été",
            type=concert_type,
            venue=self.venue,
            date_debut=starts,
            statut=Event.Statut.TENTATIVE,
            public=False,
            proposed_by=self.staff,
        )
        EventParticipation.objects.create(
            event=event,
            user=self.musician,
            status=self.statuses["invited"],
        )
        proposal = DateProposal.objects.create(
            title="Bal d’été",
            status=DateProposal.Status.DRAFT,
            linked_event=event,
            created_by=self.staff,
            deadline=timezone.localdate() + timedelta(days=3),
        )
        option = DateOption.objects.create(
            proposal=proposal,
            starts_at=starts,
            label="Matinale",
        )
        launch_availability_poll(proposal, launched_by=self.staff)
        cast_date_vote(option, self.musician, DateVote.Choice.MAYBE)

        attach_calendar_summaries([event])
        attach_open_poll_info_to_events([event], self.musician)
        summary = event.cal_summary
        self.assertTrue(summary["has_open_poll"])
        self.assertEqual(summary["my_poll_vote"], "maybe")
        self.assertEqual(summary["my_poll_vote_label"], "Peut-être")
        self.assertTrue(summary["poll_answered"])
        self.assertEqual(summary["poll_vote_counts"], {"yes": 0, "no": 0, "maybe": 1})
        self.assertEqual(summary["poll_vote_counts_label"], "Oui 0 · Non 0 · Peut-être 1")
        self.assertEqual(summary["proposed_by_label"], self.staff.get_full_name() or self.staff.username)
        self.assertEqual(
            summary["deadline_label"],
            (timezone.localdate() + timedelta(days=3)).strftime("%d/%m/%Y"),
        )

        self.client.login(username="musi", password="pass12345")
        day = timezone.localtime(starts).date()
        today = timezone.localdate()
        window_year = day.year if day.month >= today.month else day.year - 1
        r = self.client.get(
            reverse("planning:dashboard"),
            {"year": window_year, "day": day.isoformat()},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Votre réponse : Peut-être")
        self.assertContains(r, "Votre vote est enregistré")
        self.assertContains(r, "Oui 0 · Non 0 · Peut-être 1")


class StaffProposeLaunchPollTests(PlanningBaseTestCase):
    def test_staff_can_launch_poll_from_propose_form(self):
        concert_type = EventType.objects.create(nom="Concert")
        day = (timezone.localdate() + timedelta(days=20)).isoformat()
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:propose_event"),
            {
                "titre": "Nouveau bal",
                "date": day,
                "time": "20:00",
                "type_id": concert_type.pk,
                "venue_mode": "existing",
                "venue_id": self.venue.pk,
                "deadline": (timezone.localdate() + timedelta(days=10)).isoformat(),
                "launch_poll": "1",
            },
        )
        self.assertEqual(r.status_code, 302)
        event = Event.objects.get(titre="Nouveau bal")
        proposal = DateProposal.objects.get(linked_event=event)
        self.assertEqual(proposal.status, DateProposal.Status.OPEN)
        self.assertIsNotNone(proposal.launched_at)
        self.assertEqual(proposal.launched_by_id, self.staff.pk)
        self.assertEqual(
            proposal.deadline, timezone.localdate() + timedelta(days=10)
        )
        self.assertEqual(event.proposed_by_id, self.staff.pk)

    def test_staff_propose_without_launch_keeps_draft(self):
        concert_type = EventType.objects.create(nom="Concert")
        day = (timezone.localdate() + timedelta(days=21)).isoformat()
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:propose_event"),
            {
                "titre": "Brouillon sondage",
                "date": day,
                "time": "19:00",
                "type_id": concert_type.pk,
                "venue_mode": "existing",
                "venue_id": self.venue.pk,
                "deadline": (timezone.localdate() + timedelta(days=5)).isoformat(),
            },
        )
        self.assertEqual(r.status_code, 302)
        event = Event.objects.get(titre="Brouillon sondage")
        proposal = DateProposal.objects.get(linked_event=event)
        self.assertEqual(proposal.status, DateProposal.Status.DRAFT)


class PollDeadlineEditTests(PlanningBaseTestCase):
    def test_author_can_update_deadline(self):
        proposal = DateProposal.objects.create(
            title="Deadline editable",
            status=DateProposal.Status.DRAFT,
            created_by=self.musician,
            deadline=timezone.localdate() + timedelta(days=2),
            linked_event=self.event,
            deadline_reminder_sent_at=timezone.now(),
        )
        new_deadline = timezone.localdate() + timedelta(days=9)
        self.client.login(username="musi", password="pass12345")
        r = self.client.post(
            reverse("planning:update_poll_deadline", args=[proposal.pk]),
            {"deadline": new_deadline.isoformat()},
        )
        self.assertEqual(r.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.deadline, new_deadline)
        self.assertIsNone(proposal.deadline_reminder_sent_at)

    def test_other_musician_cannot_update_deadline(self):
        proposal = DateProposal.objects.create(
            title="Deadline locked",
            status=DateProposal.Status.OPEN,
            created_by=self.staff,
            deadline=timezone.localdate() + timedelta(days=2),
            linked_event=self.event,
        )
        self.client.login(username="musi", password="pass12345")
        r = self.client.post(
            reverse("planning:update_poll_deadline", args=[proposal.pk]),
            {"deadline": (timezone.localdate() + timedelta(days=20)).isoformat()},
        )
        self.assertEqual(r.status_code, 403)
        proposal.refresh_from_db()
        self.assertEqual(proposal.deadline, timezone.localdate() + timedelta(days=2))


class RosterStatusTests(PlanningBaseTestCase):
    def test_new_event_does_not_auto_invite(self):
        event = Event.objects.create(
            titre="Nouvelle date",
            type=self.event_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=21),
            statut=Event.Statut.TENTATIVE,
            public=False,
        )
        self.assertFalse(
            EventParticipation.objects.filter(event=event).exists()
        )

    def test_invite_titulaires_endpoint(self):
        # Retirer le titulaire pour retester la convocation manuelle.
        EventParticipation.objects.filter(
            event=self.event, user=self.musician
        ).delete()
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:invite_titulaires", args=[self.event.pk])
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(
            EventParticipation.objects.filter(
                event=self.event, user=self.musician
            ).exists()
        )
        part = EventParticipation.objects.get(event=self.event, user=self.musician)
        self.assertEqual(part.poste, MusicianProfile.Poste.TROMPETTE_1)
        self.assertEqual(part.role_kind, EventParticipation.RoleKind.TITULAIRE)
        self.assertFalse(
            EventParticipation.objects.filter(
                event=self.event, user=self.sub
            ).exists()
        )


class PublicationTests(PlanningBaseTestCase):
    def test_roster_organisation_form_has_parent_modes(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:event_roster", args=[self.event.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="parent_mode"')
        self.assertContains(r, 'name="parent_titre"')
        self.assertContains(r, "CMS concerts")
        self.assertNotContains(r, 'name="public"')

    def test_publication_can_create_new_parent(self):
        self.client.login(username="staff1", password="pass12345")
        before = Event.objects.count()
        r = self.client.post(
            reverse("planning:event_publication", args=[self.event.pk]),
            {
                "organisme": "Festival JOY",
                "parent_mode": "new",
                "parent_titre": "Saison jazz 2026",
            },
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Event.objects.count(), before + 1)
        self.event.refresh_from_db()
        self.assertFalse(self.event.public)
        self.assertEqual(self.event.organisme, "Festival JOY")
        self.assertIsNotNone(self.event.parent_id)
        self.assertEqual(self.event.parent.titre, "Saison jazz 2026")
        self.assertFalse(
            EventParticipation.objects.filter(event=self.event.parent).exists()
        )
        self.assertTrue(Organisme.objects.filter(nom="Festival JOY").exists())

    def test_publication_can_link_existing_parent(self):
        parent = Event.objects.create(
            titre="Festival existant",
            type=self.event_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=30),
            statut=Event.Statut.TENTATIVE,
            public=False,
        )
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:event_publication", args=[self.event.pk]),
            {
                "organisme": "",
                "parent_mode": "existing",
                "parent_id": str(parent.pk),
            },
        )
        self.assertEqual(r.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.parent_id, parent.pk)
        self.assertFalse(self.event.public)

    def test_publication_new_parent_requires_titre(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:event_publication", args=[self.event.pk]),
            {
                "parent_mode": "new",
                "parent_titre": "  ",
            },
        )
        self.assertEqual(r.status_code, 302)
        self.event.refresh_from_db()
        self.assertIsNone(self.event.parent_id)
        self.assertFalse(self.event.public)

    def test_public_toggle_is_on_cms_not_roster(self):
        self.client.login(username="staff1", password="pass12345")
        self.event.public = False
        self.event.save(update_fields=["public"])
        r = self.client.post(
            reverse("planning:event_publication", args=[self.event.pk]),
            {
                "organisme": "",
                "parent_mode": "none",
                "public": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        self.event.refresh_from_db()
        self.assertFalse(self.event.public)


class SubstituteTests(PlanningBaseTestCase):
    def test_propose_and_accept(self):
        set_participation_response(self.participation, "no")
        req = propose_substitute(self.participation, self.sub)
        self.assertEqual(req.status, SubstituteRequest.Status.PROPOSED)
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.status.code, "replacement_needed")

        respond_substitute_request(req, accept=True)
        req.refresh_from_db()
        self.assertEqual(req.status, SubstituteRequest.Status.ACCEPTED)
        sub_part = EventParticipation.objects.get(event=self.event, user=self.sub)
        self.assertEqual(sub_part.status.code, "confirmed")
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.status.code, "declined")

    def test_claim_endpoint(self):
        set_participation_response(self.participation, "no")
        req = propose_substitute(self.participation, self.sub)
        self.client.login(username="sub1", password="pass12345")
        r = self.client.post(
            reverse("planning:claim_sub", args=[req.pk]),
            data='{"accept":true}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])


class EquipmentTests(PlanningBaseTestCase):
    def test_assign_and_update_status(self):
        item = EquipmentItem.objects.create(name="Pupitre chef", category="Scène")
        assignment = EventEquipmentAssignment.objects.create(
            event=self.event,
            item=item,
            assigned_to=self.musician,
        )
        self.client.login(username="musi", password="pass12345")
        r = self.client.post(
            reverse("planning:equipment_status", args=[assignment.pk]),
            data='{"status":"ok"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, "ok")

    def test_staff_add_equipment(self):
        item = EquipmentItem.objects.create(name="Câbles", category="Sono")
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:add_event_equipment", args=[self.event.pk]),
            {"item_id": item.pk, "assigned_to": self.musician.pk},
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(
            EventEquipmentAssignment.objects.filter(
                event=self.event, item=item
            ).exists()
        )

    def test_roster_lists_default_big_band_equipment(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:event_roster", args=[self.event.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Système de sonorisation (PA)")
        self.assertContains(r, "Pupitres musiciens (lot)")
        self.assertContains(r, "+ Nouveau matériel")
        self.assertTrue(
            EquipmentItem.objects.filter(name="Câbles XLR", is_active=True).exists()
        )

    def test_staff_can_add_new_equipment_from_roster(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:add_event_equipment", args=[self.event.pk]),
            {
                "item_id": "__new__",
                "item_name": "Pied de partition pliant",
                "item_category": "Scène",
                "assigned_to": self.musician.pk,
            },
        )
        self.assertEqual(r.status_code, 302)
        item = EquipmentItem.objects.get(name="Pied de partition pliant")
        self.assertEqual(item.category, "Scène")
        self.assertTrue(
            EventEquipmentAssignment.objects.filter(
                event=self.event, item=item
            ).exists()
        )

    def test_new_equipment_rejects_unknown_category(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:add_event_equipment", args=[self.event.pk]),
            {
                "item_id": "__new__",
                "item_name": "Truc inventé",
                "item_category": "Hors catalogue",
            },
        )
        self.assertEqual(r.status_code, 302)
        self.assertFalse(
            EquipmentItem.objects.filter(name="Truc inventé").exists()
        )


class StaffAdminTests(PlanningBaseTestCase):
    def test_admin_staff_only(self):
        self.client.login(username="musi", password="pass12345")
        r = self.client.get(reverse("planning:admin"))
        self.assertIn(r.status_code, (302, 403))

        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:admin"))
        self.assertEqual(r.status_code, 200)

    def test_musicians_admin_staff_only(self):
        self.client.login(username="musi", password="pass12345")
        r = self.client.get(reverse("planning:admin_musicians"))
        self.assertIn(r.status_code, (302, 403))

        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:admin_musicians"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ada")
        self.assertContains(r, "1er trompette")

    def test_create_musician_with_dual_roles(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:admin_musician_add"),
            {
                "first_name": "Billie",
                "last_name": "Holiday",
                "email": "billie@example.com",
                "phone": "+33600000000",
                "poste_titulaire": MusicianProfile.Poste.TROMPETTE_3,
                "poste_remplacant": MusicianProfile.Poste.TROMPETTE_4,
                "poste_remplacant_2": MusicianProfile.Poste.TROMPETTE_2,
                "poste_remplacant_3": "",
                "poste_remplacant_4": "",
                "poste_remplacant_5": "",
                "is_active": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        user = User.objects.get(email="billie@example.com")
        self.assertTrue(user.is_musician)
        profile = user.musician_profile
        self.assertEqual(profile.poste_titulaire, MusicianProfile.Poste.TROMPETTE_3)
        self.assertEqual(
            profile.postes_remplacant,
            [
                MusicianProfile.Poste.TROMPETTE_4,
                MusicianProfile.Poste.TROMPETTE_2,
            ],
        )
        self.assertTrue(profile.is_titulaire)
        self.assertTrue(profile.is_remplacant)
        self.assertEqual(profile.section.code, "trompette")

    def test_create_musician_with_five_remplacant_postes(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:admin_musician_add"),
            {
                "first_name": "Cinq",
                "last_name": "Remp",
                "email": "cinqremp@example.com",
                "phone": "",
                "poste_titulaire": MusicianProfile.Poste.TROMPETTE_1,
                "poste_remplacant": MusicianProfile.Poste.TROMPETTE_2,
                "poste_remplacant_2": MusicianProfile.Poste.TROMPETTE_3,
                "poste_remplacant_3": MusicianProfile.Poste.TROMPETTE_4,
                "poste_remplacant_4": MusicianProfile.Poste.ALTO_1,
                "poste_remplacant_5": MusicianProfile.Poste.BARYTON,
                "is_active": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        profile = User.objects.get(email="cinqremp@example.com").musician_profile
        self.assertEqual(
            profile.postes_remplacant,
            [
                MusicianProfile.Poste.TROMPETTE_2,
                MusicianProfile.Poste.TROMPETTE_3,
                MusicianProfile.Poste.TROMPETTE_4,
                MusicianProfile.Poste.ALTO_1,
                MusicianProfile.Poste.BARYTON,
            ],
        )
        self.assertEqual(profile.poste_remplacant_5, MusicianProfile.Poste.BARYTON)

    def test_reject_same_poste_for_both_roles(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:admin_musician_add"),
            {
                "first_name": "Dup",
                "last_name": "Poste",
                "email": "dup@example.com",
                "phone": "",
                "poste_titulaire": MusicianProfile.Poste.PIANO,
                "poste_remplacant": MusicianProfile.Poste.PIANO,
                "poste_remplacant_2": "",
                "poste_remplacant_3": "",
                "poste_remplacant_4": "",
                "poste_remplacant_5": "",
                "is_active": "on",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email="dup@example.com").exists())

    def test_reject_duplicate_remplacant_postes(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:admin_musician_add"),
            {
                "first_name": "Dup",
                "last_name": "Remp",
                "email": "dupremp@example.com",
                "phone": "",
                "poste_titulaire": MusicianProfile.Poste.PIANO,
                "poste_remplacant": MusicianProfile.Poste.BASSE,
                "poste_remplacant_2": MusicianProfile.Poste.BASSE,
                "poste_remplacant_3": "",
                "poste_remplacant_4": "",
                "poste_remplacant_5": "",
                "is_active": "on",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email="dupremp@example.com").exists())

    def test_section_derived_from_poste_titulaire(self):
        profile = self.musician.musician_profile
        profile.poste_titulaire = MusicianProfile.Poste.ALTO_1
        profile.save()
        profile.refresh_from_db()
        self.assertEqual(profile.section.code, "sax-alto")
        profile.poste_titulaire = ""
        profile.save()
        profile.refresh_from_db()
        self.assertIsNone(profile.section_id)


class CalendarSummaryTests(PlanningBaseTestCase):
    def test_summary_counts_titulaire_and_remplacant(self):
        set_participation_response(self.participation, "yes")
        EventParticipation.objects.create(
            event=self.event,
            user=self.sub,
            status=self.statuses["confirmed"],
            comment="Remplaçant",
        )
        summary = calendar_summaries_for_events([self.event])[self.event.pk]
        self.assertEqual(summary["n_titulaires"], 1)
        self.assertEqual(summary["n_remplacants"], 1)
        self.assertEqual(summary["n_presents"], 2)
        self.assertEqual(summary["instruments_manquants"], [])
        self.assertEqual(summary["lieu"], "Salle Test — La Roche-sur-Yon")

    def test_summary_missing_section_when_no_confirmed(self):
        sax = OrchestraSection.objects.create(
            code="sax", name="Saxophones", sort_order=20
        )
        sax_player = User.objects.create_user(
            username="sax1",
            password="pass12345",
            is_musician=True,
        )
        profile = sax_player.musician_profile
        profile.section = sax
        profile.poste_titulaire = MusicianProfile.Poste.ALTO_1
        profile.save()
        summary = calendar_summaries_for_events([self.event])[self.event.pk]
        self.assertIn("Trompettes", summary["instruments_manquants"])
        self.assertIn("Saxophones altos", summary["instruments_manquants"])

    def test_summary_maybe_shows_remind_on_missing_section(self):
        remind = timezone.localdate() + timedelta(days=3)
        set_participation_response(
            self.participation,
            "maybe",
            maybe_remind_at=remind.isoformat(),
        )
        self.participation.poste = MusicianProfile.Poste.TROMPETTE_1
        self.participation.role_kind = EventParticipation.RoleKind.TITULAIRE
        self.participation.save(update_fields=["poste", "role_kind"])
        summary = calendar_summaries_for_events([self.event])[self.event.pk]
        self.assertEqual(summary["n_maybe"], 1)
        self.assertEqual(summary["n_presents"], 0)
        self.assertIn("Trompettes", summary["instruments_manquants"])
        tromp = next(
            m
            for m in summary["instruments_manquants_detail"]
            if m["name"] == "Trompettes"
        )
        self.assertEqual(len(tromp["maybe"]), 1)
        self.assertEqual(tromp["maybe"][0]["name"], "Ada Lovelace")
        self.assertEqual(tromp["maybe"][0]["remind_at"], remind)
        self.assertTrue(tromp["eligible"] or tromp["eligible"] == [])

    def test_missing_detail_lists_eligible_remplacants(self):
        summary = calendar_summaries_for_events([self.event])[self.event.pk]
        self.assertIn("Trompettes", summary["instruments_manquants"])
        tromp = next(
            d
            for d in summary["instruments_manquants_detail"]
            if d["code"] == "trompette"
        )
        eligible_ids = {e["user_id"] for e in tromp["eligible"]}
        self.assertIn(self.sub.pk, eligible_ids)
        self.assertNotIn(self.musician.pk, eligible_ids)
        slot = next(e["invite_slot"] for e in tromp["eligible"] if e["user_id"] == self.sub.pk)
        self.assertEqual(slot, f"{self.sub.pk}:trompette_2")

    def test_calendar_staff_sees_invite_button_for_missing(self):
        self.client.login(username="staff1", password="pass12345")
        year = timezone.localtime(self.event.date_debut).year
        day = timezone.localtime(self.event.date_debut).date().isoformat()
        r = self.client.get(
            reverse("planning:dashboard"),
            {"year": year, "day": day},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Trompettes")
        self.assertContains(r, "Inviter")
        self.assertContains(r, f'name="invite_slot"')
        self.assertContains(r, f"{self.sub.pk}:trompette_2")
        self.assertContains(r, "data-missing-invite-locks")
        self.assertContains(r, f'data-user-id="{self.sub.pk}"')
        self.assertContains(r, "initMissingInviteLocks")

    def test_calendar_shows_concert_and_presence_stats(self):
        from planning.services import invite_musician_to_event

        concert_type = EventType.objects.create(nom="Concert")
        concert = Event.objects.create(
            titre="Concert d’été",
            type=concert_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=21),
            statut=Event.Statut.CONFIRME,
            public=True,
        )
        part, _ = invite_musician_to_event(concert, self.musician, send_notification=False)
        set_participation_response(part, "yes")

        self.client.login(username="musi", password="pass12345")
        year = timezone.localtime(concert.date_debut).year
        r = self.client.get(reverse("planning:dashboard"), {"year": year})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Concert d’été")
        self.assertContains(r, "has-confirmed")
        self.assertContains(r, "Présents")
        self.assertContains(r, "Instruments manquants")
        self.assertContains(r, "(1 tit. · 0 remp.)")

    def test_calendar_distinguishes_proposal_from_confirmed(self):
        concert_type = EventType.objects.create(nom="Concert distingué")
        proposal = Event.objects.create(
            titre="Proposition bal",
            type=concert_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=30),
            statut=Event.Statut.TENTATIVE,
        )
        confirmed = Event.objects.create(
            titre="Concert validé",
            type=concert_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=31),
            statut=Event.Statut.CONFIRME,
        )
        summaries = calendar_summaries_for_events([proposal, confirmed, self.event])
        self.assertTrue(summaries[proposal.pk]["is_proposal"])
        self.assertEqual(summaries[proposal.pk]["layer"], "proposal")
        self.assertTrue(summaries[confirmed.pk]["is_confirmed"])
        self.assertEqual(summaries[confirmed.pk]["layer"], "confirmed")
        self.assertTrue(summaries[self.event.pk]["is_rehearsal"])
        self.assertEqual(summaries[self.event.pk]["layer"], "rehearsal")

        self.client.login(username="musi", password="pass12345")
        year = timezone.localtime(proposal.date_debut).year
        r = self.client.get(reverse("planning:dashboard"), {"year": year})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "has-proposal")
        self.assertContains(r, "has-confirmed")
        self.assertContains(r, "Proposition")
        self.assertContains(r, "Confirmé")

    def test_calendar_shows_setlist_link(self):
        from repertoire.models import Setlist

        concert_type = EventType.objects.create(nom="Concert setlist")
        concert = Event.objects.create(
            titre="Bal setlist",
            type=concert_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=25),
            statut=Event.Statut.CONFIRME,
            public=True,
        )
        sl = Setlist.objects.create(title="Programme bal", event=concert, is_active=True)

        self.client.login(username="musi", password="pass12345")
        year = timezone.localtime(concert.date_debut).year
        r = self.client.get(reverse("planning:dashboard"), {"year": year})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Setlist — Programme bal")
        self.assertContains(r, f"{reverse('planning:event_detail', args=[concert.pk])}#setlist")

        self.client.login(username="staff1", password="pass12345")
        r2 = self.client.get(reverse("planning:dashboard"), {"year": year})
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, reverse("repertoire:staff_setlist_edit", args=[sl.pk]))

    def test_calendar_shows_chat_link_with_unread(self):
        room = ChatRoom.objects.get(event=self.event)
        post_message(room=room, author=self.staff, body="Coucou orchestre")
        post_message(room=room, author=self.staff, body="Rappel pupitre")

        links = calendar_chat_links_for_user([self.event], self.musician)
        self.assertEqual(links[self.event.pk]["room_id"], room.pk)
        self.assertEqual(links[self.event.pk]["unread"], 2)

        self.client.login(username="musi", password="pass12345")
        year = timezone.localtime(self.event.date_debut).year
        r = self.client.get(reverse("planning:dashboard"), {"year": year})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f"Salon « {self.event.titre} »")
        self.assertContains(r, reverse("chat:room", args=[room.pk]))
        self.assertContains(r, 'aria-label="2 non lus"')

        detail = self.client.get(reverse("planning:event_detail", args=[self.event.pk]))
        # Répétition : détail planning redirige vers l’app répétitions.
        if detail.status_code == 302:
            detail = self.client.get(detail["Location"])
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, f"Salon « {self.event.titre} »")
        self.assertContains(detail, 'aria-label="2 non lus"')

    def test_calendar_shows_chat_link_for_staff(self):
        room = ChatRoom.objects.get(event=self.event)
        # Staff seedé dans le salon à la création.
        self.assertTrue(
            room.memberships.filter(user=self.staff, left_at__isnull=True).exists()
        )
        links = calendar_chat_links_for_user([self.event], self.staff)
        self.assertEqual(links[self.event.pk]["room_id"], room.pk)

        self.client.login(username="staff1", password="pass12345")
        year = timezone.localtime(self.event.date_debut).year
        r = self.client.get(reverse("planning:dashboard"), {"year": year})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, f"Salon « {self.event.titre} »")
        self.assertContains(r, reverse("chat:room", args=[room.pk]))


class InvitePosteChoiceTests(PlanningBaseTestCase):
    def test_invite_single_poste_auto_resolves(self):
        self.participation.delete()
        from planning.services import invite_musician_to_event

        part, created = invite_musician_to_event(
            self.event, self.musician, send_notification=False
        )
        self.assertTrue(created)
        self.assertEqual(part.poste, MusicianProfile.Poste.TROMPETTE_1)
        self.assertEqual(part.role_kind, EventParticipation.RoleKind.TITULAIRE)

    def test_invite_dual_poste_defaults_to_titulaire(self):
        dual = User.objects.create_user(
            username="dual1",
            password="pass12345",
            is_musician=True,
            first_name="Thierry",
            last_name="Chabot",
        )
        profile = dual.musician_profile
        profile.poste_titulaire = MusicianProfile.Poste.BARYTON
        profile.poste_remplacant = MusicianProfile.Poste.ALTO_1
        profile.save()
        from planning.services import invite_musician_to_event, resolve_invite_slot

        part, created = invite_musician_to_event(
            self.event, dual, send_notification=False
        )
        self.assertTrue(created)
        self.assertEqual(part.poste, MusicianProfile.Poste.BARYTON)
        self.assertEqual(part.role_kind, EventParticipation.RoleKind.TITULAIRE)

        poste, role = resolve_invite_slot(dual, MusicianProfile.Poste.ALTO_1)
        self.assertEqual(poste, MusicianProfile.Poste.ALTO_1)
        self.assertEqual(role, EventParticipation.RoleKind.REMPLACANT)

        event2 = Event.objects.create(
            titre="Autre",
            type=self.event_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=14),
            statut=Event.Statut.CONFIRME,
            public=False,
        )
        part3, created3 = invite_musician_to_event(
            event2,
            dual,
            poste=MusicianProfile.Poste.ALTO_1,
            send_notification=False,
        )
        self.assertTrue(created3)
        self.assertEqual(part3.poste, MusicianProfile.Poste.ALTO_1)
        self.assertEqual(part3.role_kind, EventParticipation.RoleKind.REMPLACANT)
        self.assertEqual(part3.poste_label, "1er alto (remp.)")
        self.assertEqual(part3.section_for_roster().code, "sax-alto")

    def test_invite_endpoint_with_slot(self):
        dual = User.objects.create_user(
            username="dual2",
            password="pass12345",
            is_musician=True,
            first_name="Jean",
            last_name="Dupont",
        )
        profile = dual.musician_profile
        profile.poste_titulaire = MusicianProfile.Poste.BARYTON
        profile.poste_remplacant = MusicianProfile.Poste.ALTO_1
        profile.save()
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:invite_musician", args=[self.event.pk]),
            {"invite_slot": f"{dual.pk}:{MusicianProfile.Poste.BARYTON}"},
        )
        self.assertEqual(r.status_code, 302)
        part = EventParticipation.objects.get(event=self.event, user=dual)
        self.assertEqual(part.poste, MusicianProfile.Poste.BARYTON)
        self.assertEqual(part.role_kind, EventParticipation.RoleKind.TITULAIRE)

    def test_roster_lists_separate_slots(self):
        dual = User.objects.create_user(
            username="dual3",
            password="pass12345",
            is_musician=True,
            first_name="Marie",
            last_name="Martin",
        )
        profile = dual.musician_profile
        profile.poste_titulaire = MusicianProfile.Poste.BARYTON
        profile.poste_remplacant = MusicianProfile.Poste.ALTO_1
        profile.save()
        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:event_roster", args=[self.event.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Marie Martin")
        self.assertContains(r, "Choisir un musicien")
        self.assertContains(r, "Titulaire par défaut")

    def test_invite_multiple_remplacant_slots(self):
        multi = User.objects.create_user(
            username="multi1",
            password="pass12345",
            is_musician=True,
            first_name="Sam",
            last_name="Multi",
        )
        profile = multi.musician_profile
        profile.poste_titulaire = MusicianProfile.Poste.BARYTON
        profile.set_postes_remplacant(
            [
                MusicianProfile.Poste.ALTO_1,
                MusicianProfile.Poste.TENOR_1,
                MusicianProfile.Poste.ALTO_2,
            ]
        )
        profile.save()
        slots = invite_slots_for_profile(profile)
        self.assertEqual(len(slots), 4)
        self.assertEqual(
            [s["poste"] for s in slots],
            [
                MusicianProfile.Poste.BARYTON,
                MusicianProfile.Poste.ALTO_1,
                MusicianProfile.Poste.TENOR_1,
                MusicianProfile.Poste.ALTO_2,
            ],
        )
        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:event_roster", args=[self.event.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Sam Multi")
        # Données JSON du formulaire (échappement unicode possible)
        self.assertContains(r, '"default_poste": "baryton"')
        self.assertContains(r, '"poste": "alto_1"')
        self.assertContains(r, '"poste": "tenor_1"')
        self.assertContains(r, '"poste": "alto_2"')
        self.assertContains(r, "Titulaire par défaut")


class RosterStageLayoutTests(PlanningBaseTestCase):
    def test_roster_by_stage_order_and_empty_chairs(self):
        stage = roster_by_stage([self.participation])
        self.assertEqual(len(stage["rows"]), 4)
        row1 = [c["poste"] for c in stage["rows"][0]]
        row2 = [c["poste"] for c in stage["rows"][1]]
        row3 = [c["poste"] for c in stage["rows"][2]]
        row4 = [c["poste"] for c in stage["rows"][3]]
        self.assertEqual(
            row1,
            [
                MusicianProfile.Poste.BARYTON,
                MusicianProfile.Poste.ALTO_2,
                MusicianProfile.Poste.ALTO_1,
                MusicianProfile.Poste.TENOR_1,
                MusicianProfile.Poste.TENOR_2,
            ],
        )
        self.assertEqual(
            row2,
            [
                MusicianProfile.Poste.TROMPETTE_4,
                MusicianProfile.Poste.TROMPETTE_3,
                MusicianProfile.Poste.TROMPETTE_1,
                MusicianProfile.Poste.TROMPETTE_2,
                MusicianProfile.Poste.CLARINETTE,
            ],
        )
        self.assertEqual(
            row3,
            [
                MusicianProfile.Poste.TROMBONE_4,
                MusicianProfile.Poste.TROMBONE_3,
                MusicianProfile.Poste.TROMBONE_1,
                MusicianProfile.Poste.TROMBONE_2,
            ],
        )
        self.assertEqual(
            row4,
            [
                MusicianProfile.Poste.CHANT,
                MusicianProfile.Poste.GUITARE,
                MusicianProfile.Poste.BATTERIE,
                MusicianProfile.Poste.BASSE,
                MusicianProfile.Poste.PIANO,
            ],
        )
        tp1 = next(
            c
            for c in stage["rows"][1]
            if c["poste"] == MusicianProfile.Poste.TROMPETTE_1
        )
        self.assertEqual(tp1["parts"], [self.participation])
        empty = next(
            c
            for c in stage["rows"][0]
            if c["poste"] == MusicianProfile.Poste.BARYTON
        )
        self.assertEqual(empty["parts"], [])
        self.assertEqual(stage["extras"], [])
        self.assertEqual(stage["unassigned"], [])

    def test_roster_extras_and_unassigned(self):
        perc = User.objects.create_user(
            username="perc1",
            password="pass12345",
            is_musician=True,
            first_name="Pat",
            last_name="Percu",
        )
        bare = User.objects.create_user(
            username="bare1",
            password="pass12345",
            is_musician=True,
            first_name="Bob",
            last_name="Sansposte",
        )
        part_perc = EventParticipation.objects.create(
            event=self.event,
            user=perc,
            status=self.statuses["confirmed"],
            poste=MusicianProfile.Poste.PERCUSSION,
            role_kind=EventParticipation.RoleKind.TITULAIRE,
        )
        part_bare = EventParticipation.objects.create(
            event=self.event,
            user=bare,
            status=self.statuses["invited"],
            poste="",
            role_kind="",
        )
        stage = roster_by_stage([self.participation, part_perc, part_bare])
        self.assertEqual(len(stage["extras"]), 1)
        self.assertEqual(stage["extras"][0]["poste"], MusicianProfile.Poste.PERCUSSION)
        self.assertEqual(stage["extras"][0]["parts"], [part_perc])
        self.assertEqual(stage["unassigned"], [part_bare])

    def test_roster_page_stage_status_classes_and_remplacant(self):
        set_participation_response(self.participation, "yes")
        remp = User.objects.create_user(
            username="remp_stage",
            password="pass12345",
            is_musician=True,
            first_name="Remy",
            last_name="Stage",
        )
        maybe_u = User.objects.create_user(
            username="maybe_stage",
            password="pass12345",
            is_musician=True,
            first_name="Maya",
            last_name="Maybe",
        )
        no_u = User.objects.create_user(
            username="no_stage",
            password="pass12345",
            is_musician=True,
            first_name="Ned",
            last_name="No",
        )
        EventParticipation.objects.create(
            event=self.event,
            user=remp,
            status=self.statuses["confirmed"],
            poste=MusicianProfile.Poste.TROMPETTE_2,
            role_kind=EventParticipation.RoleKind.REMPLACANT,
        )
        EventParticipation.objects.create(
            event=self.event,
            user=maybe_u,
            status=self.statuses["maybe"],
            poste=MusicianProfile.Poste.TROMPETTE_3,
            role_kind=EventParticipation.RoleKind.TITULAIRE,
        )
        EventParticipation.objects.create(
            event=self.event,
            user=no_u,
            status=self.statuses["declined"],
            poste=MusicianProfile.Poste.TROMPETTE_4,
            role_kind=EventParticipation.RoleKind.TITULAIRE,
        )
        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:event_roster", args=[self.event.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="pl-stage"')
        self.assertContains(r, 'data-poste="trompette_1"')
        self.assertContains(r, 'data-poste="baryton"')
        self.assertContains(r, "pl-stage__person--confirmed")
        self.assertContains(r, "pl-stage__person--maybe")
        self.assertContains(r, "pl-stage__person--declined")
        # Empty chairs keep the same red cell size as non-confirmed seats
        self.assertContains(r, "pl-stage__person--vacant")
        self.assertContains(r, "remplaçant")
        self.assertContains(r, "Ada Lovelace")
        self.assertContains(r, "Remy Stage")
        # Status color carries meaning — no Confirmé badge as primary signal
        self.assertNotContains(r, 'class="pl-badge pl-badge--success"')

    def test_remplacants_for_poste_filters_taken(self):
        eligible = remplacants_for_poste(
            MusicianProfile.Poste.TROMPETTE_2,
            taken_user_ids=set(),
        )
        self.assertTrue(any(e["user_id"] == self.sub.pk for e in eligible))
        self.assertEqual(
            next(e["invite_slot"] for e in eligible if e["user_id"] == self.sub.pk),
            f"{self.sub.pk}:trompette_2",
        )
        blocked = remplacants_for_poste(
            MusicianProfile.Poste.TROMPETTE_2,
            taken_user_ids={self.sub.pk},
        )
        self.assertFalse(any(e["user_id"] == self.sub.pk for e in blocked))

    def test_attach_roster_substitutes_on_open_chairs(self):
        stage = roster_by_stage([self.participation])
        attach_roster_substitutes(stage, taken_user_ids={self.musician.pk})
        tp1 = next(
            c
            for c in stage["rows"][1]
            if c["poste"] == MusicianProfile.Poste.TROMPETTE_1
        )
        tp2 = next(
            c
            for c in stage["rows"][1]
            if c["poste"] == MusicianProfile.Poste.TROMPETTE_2
        )
        # Invited (not confirmed) still needs a substitute proposal
        self.assertTrue(tp1["needs_substitute"])
        self.assertTrue(tp2["needs_substitute"])
        self.assertTrue(any(e["user_id"] == self.sub.pk for e in tp2["eligible"]))
        set_participation_response(self.participation, "yes")
        stage2 = roster_by_stage([self.participation])
        attach_roster_substitutes(stage2, taken_user_ids={self.musician.pk})
        tp1b = next(
            c
            for c in stage2["rows"][1]
            if c["poste"] == MusicianProfile.Poste.TROMPETTE_1
        )
        self.assertFalse(tp1b["needs_substitute"])
        self.assertEqual(tp1b["eligible"], [])

    def test_roster_page_shows_poste_substitute_invite(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:event_roster", args=[self.event.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "data-roster-invite-locks")
        self.assertContains(r, 'class="pl-stage__invite"')
        self.assertContains(r, f"{self.sub.pk}:trompette_2")
        self.assertContains(r, 'class="pl-form__actions pl-form__actions--inline"')
        self.assertContains(r, "invite-musician-form--inline")
        self.assertContains(r, "pl-form__row--gear")

    def test_invite_remplacant_from_roster_poste_cell(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.post(
            reverse("planning:invite_musician", args=[self.event.pk]),
            {"invite_slot": f"{self.sub.pk}:trompette_2"},
        )
        self.assertEqual(r.status_code, 302)
        part = EventParticipation.objects.get(event=self.event, user=self.sub)
        self.assertEqual(part.poste, MusicianProfile.Poste.TROMPETTE_2)
        self.assertEqual(part.role_kind, EventParticipation.RoleKind.REMPLACANT)


class EventPhotosRequestTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(nom="Salle", ville="Yonne")
        self.concert_type = EventType.objects.create(nom="Concert")
        self.member = User.objects.create_user(
            username="mem1",
            password="pass12345",
            email="mem1@example.com",
            is_musician=True,
        )
        self.adherent = User.objects.create_user(
            username="adh1",
            password="pass12345",
            email="adh1@example.com",
            is_association_member=True,
        )

    def test_send_event_photos_requests_marks_and_notifies(self):
        from unittest.mock import patch

        from planning.services import send_event_photos_requests

        event = Event.objects.create(
            titre="Bal photos",
            type=self.concert_type,
            venue=self.venue,
            date_debut=timezone.now() - timedelta(days=7),
            statut=Event.Statut.CONFIRME,
        )
        with patch("planning.services.invites.notify_users", return_value=2) as mocked:
            sent = send_event_photos_requests(
                [event], [self.member, self.adherent]
            )
        self.assertEqual(sent, 2)
        event.refresh_from_db()
        self.assertIsNotNone(event.photos_request_sent_at)
        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        self.assertIn(f"event={event.pk}", kwargs["url"])
        self.assertIn("Photos", kwargs["title"])

    def test_command_picks_events_from_seven_days_ago(self):
        from io import StringIO

        from django.core.management import call_command

        target = timezone.now() - timedelta(days=7)
        due = Event.objects.create(
            titre="Concert J+7",
            type=self.concert_type,
            venue=self.venue,
            date_debut=target,
            statut=Event.Statut.CONFIRME,
        )
        Event.objects.create(
            titre="Trop récent",
            type=self.concert_type,
            venue=self.venue,
            date_debut=timezone.now() - timedelta(days=2),
            statut=Event.Statut.CONFIRME,
        )
        out = StringIO()
        call_command("request_event_photos", "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertIn("Concert J+7", text)
        self.assertNotIn("Trop récent", text)
        due.refresh_from_db()
        self.assertIsNone(due.photos_request_sent_at)

    def test_media_submit_prefills_event(self):
        from core.media_events import ensure_evenement_media_for_event

        event = Event.objects.create(
            titre="Soirée jazz",
            type=self.concert_type,
            venue=self.venue,
            date_debut=timezone.now() - timedelta(days=7),
            statut=Event.Statut.CONFIRME,
        )
        media_ev = ensure_evenement_media_for_event(event)
        r = self.client.get(reverse("proposer_media"), {"event": event.pk})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Soirée jazz")
        self.assertContains(r, f'value="{media_ev.pk}"')
        self.assertContains(r, 'name="event"')
        self.assertContains(r, "sélectionné")


class MaybeRemindTests(PlanningBaseTestCase):
    @patch("planning.services.rsvp.notify_users", return_value=1)
    def test_send_due_maybe_reminds(self, mock_notify):
        from planning.services import send_due_maybe_reminds

        set_participation_response(
            self.participation, "maybe", maybe_remind_weekly=True
        )
        self.participation.maybe_remind_at = timezone.localdate()
        self.participation.save(update_fields=["maybe_remind_at"])

        treated, sent = send_due_maybe_reminds()
        self.assertEqual(treated, 1)
        self.assertEqual(sent, 1)
        mock_notify.assert_called_once()
        self.assertIn("Relance disponibilité", mock_notify.call_args.kwargs["title"])
        self.participation.refresh_from_db()
        self.assertIsNotNone(self.participation.maybe_last_reminded_at)
        self.assertEqual(
            self.participation.maybe_remind_at,
            timezone.localdate() + timedelta(days=7),
        )

    @patch("planning.services.rsvp.notify_users", return_value=1)
    def test_command_dry_run(self, mock_notify):
        from io import StringIO

        from django.core.management import call_command

        set_participation_response(
            self.participation, "maybe", maybe_remind_weekly=True
        )
        self.participation.maybe_remind_at = timezone.localdate()
        self.participation.save(update_fields=["maybe_remind_at"])
        out = StringIO()
        call_command("remind_maybe_participations", "--dry-run", stdout=out)
        self.assertIn("1 participation", out.getvalue())
        mock_notify.assert_not_called()
        self.participation.refresh_from_db()
        self.assertIsNone(self.participation.maybe_last_reminded_at)

    def test_event_detail_shows_poste_and_date(self):
        concert_type = EventType.objects.create(nom="Concert")
        self.event.type = concert_type
        self.event.save(update_fields=["type"])
        self.client.login(username="musi", password="pass12345")
        self.participation.poste = MusicianProfile.Poste.TROMPETTE_1
        self.participation.role_kind = EventParticipation.RoleKind.TITULAIRE
        self.participation.save(update_fields=["poste", "role_kind"])
        r = self.client.get(
            reverse("planning:event_detail", args=[self.event.pk])
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Votre poste")
        self.assertContains(r, "1er trompette")

    def test_event_setlist_pdf_columns_titulaire_remplacant(self):
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        from repertoire.models import Part, PartPoste, Piece, Setlist, SetlistItem

        concert_type = EventType.objects.create(nom="Concert setlist PDF")
        concert = Event.objects.create(
            titre="Bal PDF",
            type=concert_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=14),
            statut=Event.Statut.CONFIRME,
            public=True,
        )
        from planning.services import invite_musician_to_event

        invite_musician_to_event(concert, self.musician, send_notification=False)
        profile = self.musician.musician_profile
        profile.poste_titulaire = MusicianProfile.Poste.TROMPETTE_1
        profile.poste_remplacant = MusicianProfile.Poste.TROMPETTE_2
        profile.save()

        piece = Piece.objects.create(title="Take the A Train", is_published=True)
        pdf = lambda name: SimpleUploadedFile(
            name, b"%PDF-1.4\n%", content_type="application/pdf"
        )
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            part_tit = Part.objects.create(
                piece=piece, poste=PartPoste.TROMPETTE_1, file=pdf("tp1.pdf")
            )
            part_remp = Part.objects.create(
                piece=piece, poste=PartPoste.TROMPETTE_2, file=pdf("tp2.pdf")
            )
            piano = Part.objects.create(
                piece=piece, poste=PartPoste.PIANO, file=pdf("piano.pdf")
            )

            sl = Setlist.objects.create(
                title="Programme", event=concert, is_active=True
            )
            SetlistItem.objects.create(setlist=sl, piece=piece, position=1)

            self.client.login(username="musi", password="pass12345")
            url = reverse("planning:event_detail", args=[concert.pk])
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Take the A Train")
            self.assertContains(r, 'name="poste_tit"')
            self.assertContains(r, 'name="poste_remp"')
            self.assertContains(r, reverse("repertoire:part_pdf", args=[part_tit.pk]))
            self.assertContains(r, reverse("repertoire:part_pdf", args=[part_remp.pk]))

            r2 = self.client.get(
                url, {"poste_tit": "piano", "poste_remp": "trompette_1"}
            )
            self.assertEqual(r2.status_code, 200)
            self.assertContains(r2, reverse("repertoire:part_pdf", args=[piano.pk]))
            self.assertContains(r2, reverse("repertoire:part_pdf", args=[part_tit.pk]))


class PollDeadlineRemindTests(PlanningBaseTestCase):
    def _open_poll(self, *, deadline, title="Sondage J-7"):
        from planning.models import DateOption
        from planning.services import launch_availability_poll

        proposal = DateProposal.objects.create(
            title=title,
            status=DateProposal.Status.DRAFT,
            linked_event=self.event,
            created_by=self.staff,
            deadline=deadline,
        )
        DateOption.objects.create(
            proposal=proposal,
            starts_at=timezone.now() + timedelta(days=20),
            label="Option A",
        )
        launch_availability_poll(proposal, launched_by=self.staff)
        proposal.refresh_from_db()
        return proposal

    @patch("planning.services.polls.notify_users", return_value=1)
    def test_send_due_poll_deadline_reminders(self, mock_notify):
        from planning.services import send_due_poll_deadline_reminders

        due = self._open_poll(deadline=timezone.localdate() + timedelta(days=7))
        self._open_poll(
            deadline=timezone.localdate() + timedelta(days=10),
            title="Trop tôt",
        )
        mock_notify.reset_mock()

        treated, sent = send_due_poll_deadline_reminders()
        self.assertEqual(treated, 1)
        self.assertEqual(sent, 1)
        mock_notify.assert_called_once()
        self.assertIn("Rappel sondage", mock_notify.call_args.kwargs["title"])
        due.refresh_from_db()
        self.assertIsNotNone(due.deadline_reminder_sent_at)

        # Second run : déjà marqué → rien.
        treated2, sent2 = send_due_poll_deadline_reminders()
        self.assertEqual(treated2, 0)
        self.assertEqual(sent2, 0)

    @patch("planning.services.polls.notify_users", return_value=1)
    def test_skips_users_who_already_answered(self, mock_notify):
        from planning.models import DateVote
        from planning.services import cast_date_vote, send_due_poll_deadline_reminders

        proposal = self._open_poll(deadline=timezone.localdate() + timedelta(days=7))
        option = proposal.options.get()
        cast_date_vote(option, self.musician, DateVote.Choice.YES)
        mock_notify.reset_mock()

        treated, sent = send_due_poll_deadline_reminders()
        self.assertEqual(treated, 1)
        proposal.refresh_from_db()
        self.assertIsNotNone(proposal.deadline_reminder_sent_at)
        if mock_notify.called:
            users = mock_notify.call_args.args[0]
            self.assertNotIn(self.musician, users)

    @patch("planning.services.polls.notify_users", return_value=1)
    def test_command_dry_run(self, mock_notify):
        from io import StringIO

        from django.core.management import call_command

        proposal = self._open_poll(deadline=timezone.localdate() + timedelta(days=7))
        mock_notify.reset_mock()
        out = StringIO()
        call_command("remind_poll_deadlines", "--dry-run", stdout=out)
        self.assertIn("1 sondage", out.getvalue())
        mock_notify.assert_not_called()
        proposal.refresh_from_db()
        self.assertIsNone(proposal.deadline_reminder_sent_at)


class EventRoadmapTests(PlanningBaseTestCase):
    def setUp(self):
        super().setUp()
        self.concert_type = EventType.objects.create(nom="Concert")
        self.concert = Event.objects.create(
            titre="Concert Bergerie",
            type=self.concert_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=14),
            date_fin=timezone.now() + timedelta(days=14, hours=2),
            statut=Event.Statut.CONFIRME,
        )
        EventParticipation.objects.create(
            event=self.concert,
            user=self.musician,
            status=self.statuses["confirmed"],
            poste=MusicianProfile.Poste.TROMPETTE_1,
            role_kind=EventParticipation.RoleKind.TITULAIRE,
        )

    def test_staff_creates_prefilled_roadmap(self):
        from planning.services.roadmap import get_or_create_roadmap

        self.client.login(username="staff1", password="pass12345")
        url = reverse("planning:event_roadmap_edit", args=[self.concert.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Feuille de route")
        self.assertContains(r, "noir")

        roadmap = get_or_create_roadmap(self.concert)
        self.assertEqual(roadmap.dress_code, "noir")
        self.assertTrue(roadmap.material_notes)
        self.assertIsNotNone(roadmap.arrival_start)
        # Défauts : −75 / −60 / −45 / 0
        start = timezone.localtime(self.concert.date_debut)
        expected_ready = start.time().replace(second=0, microsecond=0)
        self.assertEqual(roadmap.ready_at, expected_ready)

    def test_musician_reads_roadmap_via_notification_url(self):
        from planning.services.roadmap import get_or_create_roadmap, notify_roadmap

        get_or_create_roadmap(self.concert, user=self.staff)
        with patch("planning.services.roadmap.notify_users") as mock_notify:
            mock_notify.return_value = 1
            n = notify_roadmap(self.concert)
            self.assertEqual(n, 1)
            mock_notify.assert_called_once()
            kwargs = mock_notify.call_args.kwargs
            self.assertIn("/feuille-de-route/", kwargs["url"])

        self.client.login(username="musi", password="pass12345")
        r = self.client.get(
            reverse("planning:event_roadmap", args=[self.concert.pk])
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Horaires")
        self.assertContains(r, "Matériel à prévoir")

    def test_detail_shows_roadmap_link(self):
        from planning.services.roadmap import get_or_create_roadmap

        get_or_create_roadmap(self.concert, user=self.staff)
        self.client.login(username="musi", password="pass12345")
        r = self.client.get(reverse("planning:event_detail", args=[self.concert.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Feuille de route")
        self.assertContains(
            r, reverse("planning:event_roadmap", args=[self.concert.pk])
        )

    def test_same_venue_suggests_parking(self):
        from planning.models import EventRoadmap
        from planning.services.roadmap import suggest_defaults

        EventRoadmap.objects.create(
            event=Event.objects.create(
                titre="Ancien concert",
                type=self.concert_type,
                venue=self.venue,
                date_debut=timezone.now() - timedelta(days=30),
            ),
            parking_info="Stationnement gratuit sur place",
            dress_code="noir",
            material_notes="• Instrument",
        )
        defaults = suggest_defaults(self.concert)
        self.assertEqual(defaults["parking_info"], "Stationnement gratuit sur place")
        self.assertIsNotNone(defaults["source_same_venue"])

    def test_calendar_summary_shows_roadmap_when_notified(self):
        from planning.models import EventRoadmap
        from planning.services import attach_calendar_roadmaps

        roadmap = EventRoadmap.objects.create(
            event=self.concert,
            dress_code="noir",
            material_notes="- Instrument",
            arrival_start=timezone.localtime(self.concert.date_debut).time(),
        )
        attach_calendar_roadmaps([self.concert])
        self.assertIsNone(self.concert.cal_roadmap)

        roadmap.notified_at = timezone.now()
        roadmap.save(update_fields=["notified_at"])
        attach_calendar_roadmaps([self.concert])
        self.assertEqual(self.concert.cal_roadmap["id"], roadmap.pk)

        self.client.login(username="musi", password="pass12345")
        day = timezone.localtime(self.concert.date_debut).date()
        r = self.client.get(
            reverse("planning:dashboard"),
            {"year": day.year, "day": day.isoformat()},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Feuille de route")
        self.assertContains(
            r, reverse("planning:event_roadmap", args=[self.concert.pk])
        )

    def test_roadmap_renders_chat_like_markdown(self):
        from planning.models import EventRoadmap

        EventRoadmap.objects.create(
            event=self.concert,
            parking_info="**Gratuit** sur place",
            material_notes="- Instrument\n- Partitions",
            closing_note="> Merci à tous",
            notified_at=timezone.now(),
        )
        self.client.login(username="musi", password="pass12345")
        r = self.client.get(
            reverse("planning:event_roadmap", args=[self.concert.pk])
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "<strong>Gratuit</strong>")
        self.assertContains(r, "<li>")
        self.assertContains(r, "md-cite")
        self.assertContains(r, "Merci à tous")

    def test_staff_edit_has_format_toolbar(self):
        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(
            reverse("planning:event_roadmap_edit", args=[self.concert.pk])
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-pl-md')
        self.assertContains(r, 'data-md="bold"')
        self.assertNotContains(r, "maps_url")
        self.assertContains(r, "roadmap_md.js")

    def test_staff_edit_shows_venue_map_and_gps(self):
        self.venue.adresse = "1 rue du Jazz"
        self.venue.latitude = "46.670000"
        self.venue.longitude = "-1.420000"
        self.venue.save()
        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(
            reverse("planning:event_roadmap_edit", args=[self.concert.pk])
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "1 rue du Jazz")
        self.assertContains(r, "GPS")
        self.assertContains(r, "openstreetmap.org")
        self.assertContains(r, "event-map")
        self.assertContains(r, reverse("admin_venue_edit", args=[self.venue.pk]))

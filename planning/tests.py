from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventType, Venue
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
    ensure_participation_statuses,
    propose_substitute,
    respond_substitute_request,
    set_participation_response,
)

User = get_user_model()


class PlanningBaseTestCase(TestCase):
    def setUp(self):
        self.statuses = ensure_participation_statuses()
        self.section = OrchestraSection.objects.create(
            code="trompette", name="Trompettes", sort_order=10
        )
        self.venue = Venue.objects.create(nom="Salle Test", ville="La Roche-sur-Yon")
        self.event_type = EventType.objects.create(nom="Répétition")
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
        MusicianProfile.objects.create(
            user=self.musician, section=self.section, instrument="trompette 1"
        )
        MusicianProfile.objects.create(
            user=self.sub,
            section=self.section,
            instrument="trompette 2",
            is_substitute_pool=True,
        )
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
        self.participation = EventParticipation.objects.create(
            event=self.event,
            user=self.musician,
            status=self.statuses["invited"],
        )
        self.client = Client()


class DashboardTests(PlanningBaseTestCase):
    def test_dashboard_requires_musician(self):
        outsider = User.objects.create_user(username="out", password="pass12345")
        self.client.login(username="out", password="pass12345")
        r = self.client.get(reverse("planning:dashboard"))
        self.assertIn(r.status_code, (302, 403))

    def test_dashboard_ok(self):
        self.client.login(username="musi", password="pass12345")
        r = self.client.get(reverse("planning:dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Répète vendredi")


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


class PollTests(PlanningBaseTestCase):
    def test_create_and_vote_and_lock(self):
        self.client.login(username="staff1", password="pass12345")
        starts = (timezone.now() + timedelta(days=14)).strftime("%Y-%m-%dT20:00")
        r = self.client.post(
            reverse("planning:create_poll"),
            {
                "title": "Choix date mars",
                "description": "Test",
                "option_starts_0": starts,
                "option_label_0": "Vendredi",
            },
        )
        self.assertEqual(r.status_code, 302)
        proposal = DateProposal.objects.get(title="Choix date mars")
        option = proposal.options.get()

        self.client.login(username="musi", password="pass12345")
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
                "venue_id": self.venue.pk,
                "type_id": self.event_type.pk,
            },
        )
        self.assertEqual(r.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, DateProposal.Status.LOCKED)
        self.assertIsNotNone(proposal.linked_event)


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


class StaffAdminTests(PlanningBaseTestCase):
    def test_admin_staff_only(self):
        self.client.login(username="musi", password="pass12345")
        r = self.client.get(reverse("planning:admin"))
        self.assertIn(r.status_code, (302, 403))

        self.client.login(username="staff1", password="pass12345")
        r = self.client.get(reverse("planning:admin"))
        self.assertEqual(r.status_code, 200)

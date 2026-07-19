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
    calendar_summaries_for_events,
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
            user=self.musician,
            section=self.section,
            poste_titulaire=MusicianProfile.Poste.TROMPETTE_1,
        )
        MusicianProfile.objects.create(
            user=self.sub,
            section=self.section,
            poste_remplacant=MusicianProfile.Poste.TROMPETTE_2,
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
        # Signal : les titulaires sont déjà convoqués à la création.
        self.participation = EventParticipation.objects.get(
            event=self.event,
            user=self.musician,
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
        year = timezone.localdate().year
        r = self.client.get(reverse("planning:dashboard"), {"year": year})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Janvier")
        self.assertContains(r, "Décembre")
        self.assertContains(r, "Répète vendredi")
        self.assertEqual(len(r.context["months"]), 12)

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
                "venue_id": self.venue.pk,
                "type_id": self.event_type.pk,
            },
        )
        self.assertEqual(r.status_code, 302)
        event = Event.objects.get(titre="Nouveau concert")
        self.assertTrue(
            EventParticipation.objects.filter(
                event=event, user=self.musician
            ).exists()
        )


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
        event = proposal.linked_event
        self.assertTrue(
            EventParticipation.objects.filter(
                event=event, user=self.musician
            ).exists()
        )
        self.assertFalse(
            EventParticipation.objects.filter(event=event, user=self.sub).exists()
        )


class RosterStatusTests(PlanningBaseTestCase):
    def test_new_event_invites_titulaires_only(self):
        event = Event.objects.create(
            titre="Nouvelle date",
            type=self.event_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=21),
            statut=Event.Statut.TENTATIVE,
            public=False,
        )
        invited_ids = set(
            EventParticipation.objects.filter(event=event).values_list(
                "user_id", flat=True
            )
        )
        self.assertIn(self.musician.pk, invited_ids)
        self.assertNotIn(self.sub.pk, invited_ids)

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
        self.assertFalse(
            EventParticipation.objects.filter(
                event=self.event, user=self.sub
            ).exists()
        )


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
                "is_active": "on",
            },
        )
        self.assertEqual(r.status_code, 302)
        user = User.objects.get(email="billie@example.com")
        self.assertTrue(user.is_musician)
        profile = user.musician_profile
        self.assertEqual(profile.poste_titulaire, MusicianProfile.Poste.TROMPETTE_3)
        self.assertEqual(profile.poste_remplacant, MusicianProfile.Poste.TROMPETTE_4)
        self.assertTrue(profile.is_titulaire)
        self.assertTrue(profile.is_remplacant)
        self.assertEqual(profile.section.code, "trompette")

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
                "is_active": "on",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email="dup@example.com").exists())

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
        MusicianProfile.objects.create(
            user=sax_player,
            section=sax,
            poste_titulaire=MusicianProfile.Poste.ALTO_1,
        )
        summary = calendar_summaries_for_events([self.event])[self.event.pk]
        self.assertIn("Trompettes", summary["instruments_manquants"])
        self.assertIn("Saxophones altos", summary["instruments_manquants"])

    def test_calendar_shows_concert_and_presence_stats(self):
        concert_type = EventType.objects.create(nom="Concert")
        concert = Event.objects.create(
            titre="Concert d’été",
            type=concert_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=21),
            statut=Event.Statut.CONFIRME,
            public=True,
        )
        part = EventParticipation.objects.get(event=concert, user=self.musician)
        set_participation_response(part, "yes")

        self.client.login(username="musi", password="pass12345")
        year = timezone.localtime(concert.date_debut).year
        r = self.client.get(reverse("planning:dashboard"), {"year": year})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Concert d’été")
        self.assertContains(r, "has-concert")
        self.assertContains(r, "Présents")
        self.assertContains(r, "Instruments manquants")
        self.assertContains(r, "(1 tit. · 0 remp.)")

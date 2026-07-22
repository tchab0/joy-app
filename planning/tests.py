from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from chat.models import ChatRoom
from chat.services import post_message
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
    calendar_chat_links_for_user,
    calendar_summaries_for_events,
    ensure_participation_statuses,
    invite_slots_for_profile,
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
        self.assertEqual(proposal.status, DateProposal.Status.DRAFT)
        option = proposal.options.get()

        # Lancement staff requis avant vote.
        r = self.client.post(reverse("planning:launch_poll", args=[proposal.pk]))
        self.assertEqual(r.status_code, 302)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, DateProposal.Status.OPEN)

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
        # Verrouillage ne convoque plus automatiquement.
        self.assertFalse(
            EventParticipation.objects.filter(
                event=event, user=self.musician
            ).exists()
        )

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
        self.assertContains(r, "has-concert")
        self.assertContains(r, "Présents")
        self.assertContains(r, "Instruments manquants")
        self.assertContains(r, "(1 tit. · 0 remp.)")

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

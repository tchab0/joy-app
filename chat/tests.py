from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from chat.models import ChatMembership, ChatMessageReaction, ChatRoom
from chat.services import (
    ensure_orchestra_room,
    post_message,
    serialize_message,
    sync_musician_to_orchestra,
    toggle_reaction,
)
from events.models import Event, EventType, Venue
from planning.models import EventParticipation, MusicianProfile
from planning.services import ensure_participation_statuses, get_status

User = get_user_model()


@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
    SMS_BACKEND="console",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class ChatCoreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_participation_statuses()
        cls.venue = Venue.objects.create(nom="Salle Test", ville="La Roche-sur-Yon")
        cls.etype = EventType.objects.create(nom="Répétition")
        cls.musician = User.objects.create_user(
            username="chat_musi",
            password="pass",
            email="chat_musi@example.com",
            is_musician=True,
            phone="+33601020304",
            chat_auto_subscribe=True,
        )
        profile = cls.musician.musician_profile
        profile.poste_titulaire = MusicianProfile.Poste.TROMPETTE_1
        profile.save()
        cls.other = User.objects.create_user(
            username="chat_other",
            password="pass",
            email="chat_other@example.com",
            is_musician=True,
            phone="+33601020305",
            chat_auto_subscribe=True,
        )
        other_profile = cls.other.musician_profile
        other_profile.poste_titulaire = MusicianProfile.Poste.TROMPETTE_2
        other_profile.save()

    def test_orchestra_room_on_musician(self):
        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        m = ChatMembership.objects.get(room=room, user=self.musician)
        self.assertIsNone(m.left_at)
        self.assertTrue(m.subscribed)

    def test_event_creates_staff_only_room(self):
        staff = User.objects.create_user(
            username="chat_staff",
            password="pass",
            is_staff=True,
            is_musician=True,
        )
        event = Event.objects.create(
            titre="Concert chat",
            type=self.etype,
            venue=self.venue,
            date_debut="2030-06-01T20:00:00+02:00",
            statut="confirme",
        )
        room = ChatRoom.objects.get(event=event)
        self.assertEqual(room.kind, ChatRoom.Kind.EVENT)
        # Plus de convocation auto → salon staff uniquement.
        self.assertFalse(
            EventParticipation.objects.filter(event=event, user=self.musician).exists()
        )
        self.assertFalse(
            ChatMembership.objects.filter(room=room, user=self.musician).exists()
        )
        self.assertTrue(
            ChatMembership.objects.filter(
                room=room, user=staff, left_at__isnull=True
            ).exists()
        )

    def test_auto_subscribe_respects_pref(self):
        from planning.services import invite_musician_to_event

        self.musician.chat_auto_subscribe = False
        self.musician.save(update_fields=["chat_auto_subscribe"])
        event = Event.objects.create(
            titre="Sans notification",
            type=self.etype,
            venue=self.venue,
            date_debut="2030-07-01T20:00:00+02:00",
            statut="confirme",
        )
        invite_musician_to_event(event, self.musician, send_notification=False)
        room = ChatRoom.objects.get(event=event)
        membership = ChatMembership.objects.get(room=room, user=self.musician)
        self.assertFalse(membership.subscribed)

    def test_unsubscribe_keeps_membership(self):
        room = ensure_orchestra_room()
        m = sync_musician_to_orchestra(self.musician)
        m.subscribed = False
        m.save(update_fields=["subscribed"])
        m.refresh_from_db()
        self.assertIsNone(m.left_at)
        self.assertFalse(m.subscribed)

    def test_leave_and_rejoin(self):
        from planning.services import invite_musician_to_event

        event = Event.objects.create(
            titre="Quitter",
            type=self.etype,
            venue=self.venue,
            date_debut="2030-08-01T20:00:00+02:00",
            statut="confirme",
        )
        part, _ = invite_musician_to_event(event, self.musician, send_notification=False)
        part.status = get_status("declined")
        part.save(update_fields=["status"])
        room = ChatRoom.objects.get(event=event)
        membership = ChatMembership.objects.get(room=room, user=self.musician)
        membership.leave()
        membership.refresh_from_db()
        self.assertIsNotNone(membership.left_at)
        self.assertFalse(membership.subscribed)

        client = Client()
        client.login(username="chat_musi", password="pass")
        r = client.post(reverse("chat:rejoin", args=[room.pk]))
        self.assertEqual(r.status_code, 302)
        membership.refresh_from_db()
        self.assertIsNone(membership.left_at)

    def test_room_list_requires_musician(self):
        outsider = User.objects.create_user(username="outsider", password="pass")
        client = Client()
        client.login(username="outsider", password="pass")
        r = client.get(reverse("chat:list"))
        self.assertEqual(r.status_code, 403)

    def test_event_room_shows_event_intro(self):
        from planning.services import invite_musician_to_event

        event = Event.objects.create(
            titre="Concert intro",
            type=self.etype,
            venue=self.venue,
            date_debut="2030-09-15T20:00:00+02:00",
            statut="confirme",
            organisme="Festival Test",
        )
        invite_musician_to_event(event, self.musician, send_notification=False)
        room = ChatRoom.objects.get(event=event)
        client = Client()
        client.login(username="chat_musi", password="pass")
        r = client.get(reverse("chat:room", args=[room.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Infos de l’événement")
        self.assertContains(r, "Salle Test")
        self.assertContains(r, "Festival Test")
        self.assertContains(r, "Voir le détail planning")
        self.assertContains(r, reverse("planning:event_detail", args=[event.pk]))

    def test_post_message_and_attachment(self):
        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        msg = post_message(room=room, author=self.musician, body="Hello")
        self.assertEqual(msg.body, "Hello")

        f = SimpleUploadedFile(
            "score.pdf", b"%PDF-1.4 test", content_type="application/pdf"
        )
        msg2 = post_message(room=room, author=self.musician, body="", files=[f])
        self.assertEqual(msg2.attachments.count(), 1)

    def test_digest_command(self):
        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        sync_musician_to_orchestra(self.other)
        post_message(room=room, author=self.other, body="Ping digest")

        out = StringIO()
        call_command("chat_send_digests", stdout=out)
        membership = ChatMembership.objects.get(room=room, user=self.musician)
        self.assertGreater(membership.last_digested_message_id, 0)

    def test_chat_prefs_view(self):
        client = Client()
        client.login(username="chat_musi", password="pass")
        r = client.get(reverse("chat:prefs"))
        self.assertEqual(r.status_code, 200)
        r = client.post(reverse("chat:prefs"), {"chat_auto_subscribe": False})
        self.assertEqual(r.status_code, 302)
        self.musician.refresh_from_db()
        self.assertFalse(self.musician.chat_auto_subscribe)

    def test_message_reactions_like_and_hide(self):
        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        sync_musician_to_orchestra(self.other)
        msg = post_message(room=room, author=self.other, body="Réagissez")

        up = toggle_reaction(
            message=msg, user=self.musician, value=ChatMessageReaction.Value.UP
        )
        self.assertEqual(up["likes"], 1)
        self.assertEqual(up["mine"], "up")
        self.assertFalse(up["hidden"])

        client = Client()
        client.login(username="chat_musi", password="pass")
        r = client.post(
            reverse("chat:api_react", args=[room.pk]),
            {"message_id": msg.pk, "value": "down"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["likes"], 0)
        self.assertEqual(data["mine"], "down")
        self.assertTrue(data["hidden"])

        msg.refresh_from_db()
        payload = serialize_message(msg, viewer=self.musician)
        self.assertTrue(payload["hidden"])
        self.assertEqual(payload["likes"], 0)
        payload_other = serialize_message(msg, viewer=self.other)
        self.assertFalse(payload_other["hidden"])

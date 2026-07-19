from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from chat.models import ChatMembership, ChatRoom
from chat.services import (
    ensure_orchestra_room,
    post_message,
    sync_musician_to_orchestra,
)
from events.models import Event, EventType, Venue
from planning.models import EventParticipation, MusicianProfile
from planning.services import ensure_participation_statuses, get_status

User = get_user_model()


@override_settings(
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
    SMS_BACKEND="console",
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
            is_musician=True,
            phone="+33601020304",
            chat_auto_subscribe=True,
        )
        MusicianProfile.objects.create(
            user=cls.musician,
            poste_titulaire=MusicianProfile.Poste.TROMPETTE_1,
        )
        cls.other = User.objects.create_user(
            username="chat_other",
            password="pass",
            is_musician=True,
            phone="+33601020305",
            chat_auto_subscribe=True,
        )
        MusicianProfile.objects.create(
            user=cls.other,
            poste_titulaire=MusicianProfile.Poste.TROMPETTE_2,
        )

    def test_orchestra_room_on_musician(self):
        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        m = ChatMembership.objects.get(room=room, user=self.musician)
        self.assertIsNone(m.left_at)
        self.assertTrue(m.subscribed)

    def test_event_creates_room_and_membership(self):
        event = Event.objects.create(
            titre="Concert chat",
            type=self.etype,
            venue=self.venue,
            date_debut="2030-06-01T20:00:00+02:00",
            statut="confirme",
        )
        room = ChatRoom.objects.get(event=event)
        self.assertEqual(room.kind, ChatRoom.Kind.EVENT)
        # Signal planning invite déjà les titulaires → membership chat créé.
        part = EventParticipation.objects.get(event=event, user=self.musician)
        membership = ChatMembership.objects.get(room=room, user=self.musician)
        self.assertTrue(membership.subscribed)
        self.assertIsNone(membership.left_at)
        self.assertEqual(part.user_id, self.musician.pk)

    def test_auto_subscribe_respects_pref(self):
        self.musician.chat_auto_subscribe = False
        self.musician.save(update_fields=["chat_auto_subscribe"])
        event = Event.objects.create(
            titre="Sans SMS",
            type=self.etype,
            venue=self.venue,
            date_debut="2030-07-01T20:00:00+02:00",
            statut="confirme",
        )
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
        event = Event.objects.create(
            titre="Quitter",
            type=self.etype,
            venue=self.venue,
            date_debut="2030-08-01T20:00:00+02:00",
            statut="confirme",
        )
        part = EventParticipation.objects.get(event=event, user=self.musician)
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

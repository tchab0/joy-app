from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from chat.models import ChatMembership, ChatMessage, ChatMessageReaction, ChatRoom
from chat.services import (
    assign_mention_handles,
    chat_room_url,
    delete_message,
    ensure_event_room,
    ensure_orchestra_room,
    ensure_rehearsal_setlist_tip,
    ensure_section_rooms,
    ensure_staff_room,
    edit_message,
    extract_mention_tokens,
    musician_section_keys,
    post_message,
    replies_prefetch,
    resolve_mentioned_users,
    serialize_mention_members,
    serialize_message,
    sync_musician_to_orchestra,
    sync_musician_to_section_rooms,
    sync_user_to_staff_room,
    toggle_reaction,
    unread_count,
    user_can_access_room,
    REHEARSAL_SETLIST_TIP_PREFIX,
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

    def test_staff_room_staff_only(self):
        staff = User.objects.create_user(
            username="chat_staff_room",
            password="pass",
            is_staff=True,
            is_musician=True,
        )
        room = ensure_staff_room()
        self.assertEqual(room.kind, ChatRoom.Kind.STAFF)
        staff_m = ChatMembership.objects.get(room=room, user=staff, left_at__isnull=True)
        self.assertTrue(staff_m.subscribed)
        self.assertFalse(
            ChatMembership.objects.filter(room=room, user=self.musician).exists()
        )
        self.assertTrue(user_can_access_room(staff, room))
        self.assertFalse(user_can_access_room(self.musician, room))

        client = Client()
        client.login(username="chat_musi", password="pass")
        r = client.get(reverse("chat:staff"))
        self.assertEqual(r.status_code, 403)
        r = client.get(reverse("chat:room", args=[room.pk]))
        self.assertEqual(r.status_code, 403)

        client.login(username="chat_staff_room", password="pass")
        r = client.get(reverse("chat:staff"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("chat:room", args=[room.pk]))
        sync_user_to_staff_room(staff)
        r = client.get(reverse("chat:list"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Staff")
        self.assertContains(r, reverse("chat:room", args=[room.pk]))

    def test_section_rooms_by_poste_and_chant_in_all(self):
        rooms = {r.section_key: r for r in ensure_section_rooms()}
        self.assertEqual(
            set(rooms),
            {"sax", "trompettes", "trombones", "rythmique"},
        )
        self.assertEqual(rooms["trompettes"].title, "Trompettes & clarinette")

        # Trompettistes → salon trompettes seulement
        sync_musician_to_section_rooms(self.musician)
        sync_musician_to_section_rooms(self.other)
        self.assertEqual(musician_section_keys(self.musician), {"trompettes"})
        self.assertTrue(
            ChatMembership.objects.filter(
                room=rooms["trompettes"],
                user=self.musician,
                left_at__isnull=True,
            ).exists()
        )
        self.assertFalse(
            ChatMembership.objects.filter(
                room=rooms["sax"],
                user=self.musician,
                left_at__isnull=True,
            ).exists()
        )

        # Chanteuse → les 4 salons
        singer = User.objects.create_user(
            username="chat_chant",
            password="pass",
            email="chant@example.com",
            is_musician=True,
            chat_auto_subscribe=True,
        )
        sp = singer.musician_profile
        sp.poste_titulaire = MusicianProfile.Poste.CHANT
        sp.save()
        sync_musician_to_section_rooms(singer)
        self.assertEqual(
            musician_section_keys(singer),
            {"sax", "trompettes", "trombones", "rythmique"},
        )
        for key in rooms:
            self.assertTrue(
                ChatMembership.objects.filter(
                    room=rooms[key], user=singer, left_at__isnull=True
                ).exists(),
                msg=f"chanteuse absente de {key}",
            )

        # Clarinette → même salon que trompettes
        clar = User.objects.create_user(
            username="chat_clar",
            password="pass",
            is_musician=True,
        )
        cp = clar.musician_profile
        cp.poste_titulaire = MusicianProfile.Poste.CLARINETTE
        cp.save()
        sync_musician_to_section_rooms(clar)
        self.assertEqual(musician_section_keys(clar), {"trompettes"})

        # Changement de poste → soft-leave / rejoin
        profile = self.musician.musician_profile
        profile.poste_titulaire = MusicianProfile.Poste.BARYTON
        profile.save()
        sync_musician_to_section_rooms(self.musician)
        self.assertEqual(musician_section_keys(self.musician), {"sax"})
        self.assertTrue(
            ChatMembership.objects.filter(
                room=rooms["sax"], user=self.musician, left_at__isnull=True
            ).exists()
        )
        left_tp = ChatMembership.objects.get(
            room=rooms["trompettes"], user=self.musician
        )
        self.assertIsNotNone(left_tp.left_at)

        # Salon pupitre non quittable
        client = Client()
        client.login(username="chat_chant", password="pass")
        r = client.post(
            reverse("chat:room", args=[rooms["sax"].pk]),
            {"action": "leave"},
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(
            ChatMembership.objects.filter(
                room=rooms["sax"], user=singer, left_at__isnull=True
            ).exists()
        )

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
        staff_m = ChatMembership.objects.get(
            room=room, user=staff, left_at__isnull=True
        )
        self.assertTrue(staff_m.subscribed)

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

    def test_room_list_handles_system_last_message(self):
        """Messages système (author=None) ne doivent pas faire planter /chat/."""
        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        post_message(
            room=room,
            author=None,
            body="Message système de bienvenue",
            kind=ChatMessage.Kind.SYSTEM,
        )
        client = Client()
        client.login(username="chat_musi", password="pass")
        r = client.get(reverse("chat:list"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Système")
        self.assertContains(r, "Message système de bienvenue")

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

    def test_room_detail_does_not_leak_history_as_flash(self):
        """Collision django.contrib.messages : l’historique ne doit pas s’afficher en haut."""
        from django.contrib.messages.storage.fallback import FallbackStorage

        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        sync_musician_to_orchestra(self.other)
        body = "C'est ici que vous pouvez m'envoyer des remarques"
        msg = post_message(room=room, author=self.other, body=body)
        client = Client()
        client.login(username="chat_musi", password="pass")
        r = client.get(reverse("chat:room", args=[room.pk]))
        self.assertEqual(r.status_code, 200)
        # Présent dans le JSON du fil, pas comme flash « #id preview ».
        self.assertContains(r, body)
        self.assertNotContains(r, f"#{msg.pk} {body[:40]}")
        self.assertIsInstance(r.context["messages"], FallbackStorage)
        self.assertIn("messages_data", r.context)
        self.assertEqual(len(r.context["messages_data"]), 1)

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

        f2 = SimpleUploadedFile(
            "notes.txt", b"hello notes", content_type="text/plain"
        )
        f3 = SimpleUploadedFile(
            "score2.pdf", b"%PDF-1.4 two", content_type="application/pdf"
        )
        msg3 = post_message(
            room=room, author=self.musician, body="multi", files=[f2, f3]
        )
        self.assertEqual(msg3.attachments.count(), 2)

    def test_edit_message_attachments(self):
        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        f1 = SimpleUploadedFile(
            "a.pdf", b"%PDF-1.4 a", content_type="application/pdf"
        )
        f2 = SimpleUploadedFile(
            "b.txt", b"bbb", content_type="text/plain"
        )
        msg = post_message(
            room=room, author=self.musician, body="avec PJ", files=[f1, f2]
        )
        self.assertEqual(msg.attachments.count(), 2)
        ids = list(msg.attachments.order_by("pk").values_list("pk", flat=True))

        edited = edit_message(
            message=msg,
            editor=self.musician,
            body="sans une",
            remove_attachment_ids=[ids[0]],
        )
        self.assertEqual(edited.attachments.count(), 1)
        self.assertEqual(edited.attachments.first().pk, ids[1])

        f3 = SimpleUploadedFile(
            "c.pdf", b"%PDF-1.4 c", content_type="application/pdf"
        )
        edited2 = edit_message(
            message=edited,
            editor=self.musician,
            body="",
            files=[f3],
        )
        self.assertEqual(edited2.body, "")
        self.assertEqual(edited2.attachments.count(), 2)

        # Vider totalement → refusé
        rem = list(edited2.attachments.values_list("pk", flat=True))
        with self.assertRaises(ValueError):
            edit_message(
                message=edited2,
                editor=self.musician,
                body="",
                remove_attachment_ids=rem,
            )

        client = Client()
        client.login(username="chat_musi", password="pass")
        f4 = SimpleUploadedFile(
            "d.txt", b"ddd", content_type="text/plain"
        )
        r = client.post(
            reverse("chat:api_edit", args=[room.pk]),
            {
                "message_id": edited2.pk,
                "body": "api edit",
                "remove_attachment_ids": rem[:1],
                "files": f4,
            },
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"]["body"], "api edit")
        self.assertEqual(len(data["message"]["attachments"]), 2)

    def test_author_can_delete_own_message(self):
        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        sync_musician_to_orchestra(self.other)
        msg = post_message(room=room, author=self.musician, body="À effacer")
        reply_before = post_message(
            room=room,
            author=self.other,
            body="Réponse avant suppression",
            reply_to=msg,
        )

        with self.assertRaises(ValueError):
            delete_message(message=msg, actor=self.other)

        deleted = delete_message(message=msg, actor=self.musician)
        self.assertTrue(deleted.is_deleted)
        payload = serialize_message(deleted, viewer=self.other)
        self.assertTrue(payload["deleted"])
        self.assertEqual(payload["body"], "")
        self.assertEqual(payload["attachments"], [])

        # Soft-deleted : absent de l’historique salon (pas de placeholder UI).
        self.assertFalse(
            ChatMessage.objects.filter(
                room=room, deleted_at__isnull=True, pk=deleted.pk
            ).exists()
        )

        reply_payload = serialize_message(
            ChatMessage.objects.select_related("reply_to", "reply_to__author")
            .prefetch_related("reply_to__attachments")
            .get(pk=reply_before.pk),
            viewer=self.other,
        )
        self.assertEqual(reply_payload["reply_to"]["body_preview"], "…")
        self.assertTrue(reply_payload["reply_to"]["deleted"])

        with self.assertRaises(ValueError):
            delete_message(message=deleted, actor=self.musician)

        client = Client()
        client.login(username="chat_musi", password="pass")
        other_msg = post_message(room=room, author=self.musician, body="Via API")
        r = client.post(
            reverse("chat:api_delete", args=[room.pk]),
            {"message_id": other_msg.pk},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["message"]["deleted"])

        client.logout()
        client.login(username="chat_other", password="pass")
        third = post_message(room=room, author=self.musician, body="Pas à toi")
        r = client.post(
            reverse("chat:api_delete", args=[room.pk]),
            {"message_id": third.pk},
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])

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
        self.assertContains(r, "Réponses à mes messages")
        r = client.post(
            reverse("chat:prefs"),
            {
                "notify_frequency": "realtime",
                "notify_digest_hour": 18,
                "notify_digest_weekday": 0,
                "chat_auto_subscribe": False,
            },
        )
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

    def test_reply_to_message(self):
        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        sync_musician_to_orchestra(self.other)
        parent = post_message(room=room, author=self.other, body="Question initiale")
        reply = post_message(
            room=room,
            author=self.musician,
            body="Voici ma réponse",
            reply_to=parent,
        )
        self.assertEqual(reply.reply_to_id, parent.pk)
        payload = serialize_message(reply, viewer=self.musician)
        self.assertIsNotNone(payload["reply_to"])
        self.assertEqual(payload["reply_to"]["id"], parent.pk)
        self.assertTrue(payload["reply_to"]["author_name"])
        self.assertEqual(payload["reply_to"]["body_preview"], "Question initiale")

        parent_payload = serialize_message(
            ChatMessage.objects.get(pk=parent.pk), viewer=self.musician
        )
        self.assertEqual(parent_payload["replies_count"], 1)
        self.assertEqual(parent_payload["first_reply_id"], reply.pk)

        client = Client()
        client.login(username="chat_musi", password="pass")
        r = client.post(
            reverse("chat:api_send", args=[room.pk]),
            {"body": "Via API", "reply_to_id": parent.pk},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"]["reply_to"]["id"], parent.pk)

        parent_payload = serialize_message(
            ChatMessage.objects.prefetch_related(replies_prefetch()).get(pk=parent.pk),
            viewer=self.musician,
        )
        self.assertEqual(parent_payload["replies_count"], 2)
        self.assertEqual(parent_payload["first_reply_id"], reply.pk)

        # ID invalide / autre salon → message sans reply
        orphan = post_message(
            room=room, author=self.musician, body="Sans parent", reply_to_id=999999
        )
        self.assertIsNone(orphan.reply_to_id)
        orphan_payload = serialize_message(orphan, viewer=self.musician)
        self.assertEqual(orphan_payload["replies_count"], 0)
        self.assertIsNone(orphan_payload["first_reply_id"])

    def test_mention_resolve_and_notify(self):
        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        sync_musician_to_orchestra(self.other)

        self.assertEqual(
            extract_mention_tokens("@chat_other salut\n@inconnu"),
            ["chat_other", "inconnu"],
        )
        # Préfixe incomplet (comme @thierry.b) → pas de match
        self.assertEqual(
            resolve_mentioned_users(room, "@chat_oth hello", exclude_user=self.musician),
            [],
        )
        matched = resolve_mentioned_users(
            room, "Coucou @chat_other !", exclude_user=self.musician
        )
        self.assertEqual([u.pk for u in matched], [self.other.pk])

        # @Prénom (handle) aussi résolu
        other_handle = assign_mention_handles(
            [self.musician, self.other]
        )[self.other.pk]
        matched_handle = resolve_mentioned_users(
            room, f"Coucou @{other_handle} !", exclude_user=self.musician
        )
        self.assertEqual([u.pk for u in matched_handle], [self.other.pk])

        from unittest.mock import patch

        with patch("users.notify.notify_users", return_value=1) as notify:
            post_message(
                room=room,
                author=self.musician,
                body="@chat_other tu es là ?",
            )
            self.assertTrue(notify.called)
            args, kwargs = notify.call_args
            users = list(args[0])
            self.assertEqual([u.pk for u in users], [self.other.pk])
            self.assertNotIn(self.musician.pk, [u.pk for u in users])
            self.assertIn("cité", kwargs["body"])

        with patch("users.notify.notify_users", return_value=1) as notify:
            parent = post_message(room=room, author=self.other, body="Ping")
            notify.reset_mock()
            post_message(
                room=room,
                author=self.musician,
                body="Réponse sans @",
                reply_to=parent,
            )
            self.assertTrue(notify.called)
            users = list(notify.call_args[0][0])
            self.assertEqual([u.pk for u in users], [self.other.pk])
            self.assertNotIn(self.musician.pk, [u.pk for u in users])
            kwargs = notify.call_args[1]
            self.assertEqual(kwargs.get("notify_type"), "chat_reply")
            self.assertFalse(kwargs.get("force_immediate"))
            self.assertIn("répondu", kwargs["body"])

        # L’auteur ne reçoit aucune notif pour son propre message
        # (ni message simple, ni auto-@mention, ni auto-réponse)
        with patch("users.notify.notify_users", return_value=1) as notify:
            post_message(
                room=room,
                author=self.musician,
                body="Message sans destinataire",
            )
            self.assertFalse(notify.called)

        with patch("users.notify.notify_users", return_value=1) as notify:
            post_message(
                room=room,
                author=self.musician,
                body="@chat_musi hello moi",
            )
            self.assertFalse(notify.called)

        with patch("users.notify.notify_users", return_value=1) as notify:
            own = post_message(room=room, author=self.musician, body="Parent")
            notify.reset_mock()
            post_message(
                room=room,
                author=self.musician,
                body="Réponse à moi-même",
                reply_to=own,
            )
            self.assertFalse(notify.called)

        client = Client()
        client.login(username="chat_musi", password="pass")
        r = client.get(reverse("chat:room", args=[room.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "chat-members-")
        self.assertContains(r, "chat_other")

    def test_mention_handles_disambiguate_same_first_name(self):
        a = User.objects.create_user(
            username="stephane.gallet",
            password="pass",
            first_name="Stéphane",
            last_name="Gallet",
            is_musician=True,
        )
        b = User.objects.create_user(
            username="stephane.poussin",
            password="pass",
            first_name="Stéphane",
            last_name="Poussin",
            is_musician=True,
        )
        c = User.objects.create_user(
            username="adrien.pubert",
            password="pass",
            first_name="Adrien",
            last_name="Pubert",
            is_musician=True,
        )
        handles = assign_mention_handles([a, b, c])
        self.assertEqual(handles[c.pk], "Adrien")
        self.assertEqual(handles[a.pk], "Stéphane G")
        self.assertEqual(handles[b.pk], "Stéphane P")

        # Préfixe plus long si la 1re lettre du nom est identique
        d1 = User.objects.create_user(
            username="jean.dupont",
            password="pass",
            first_name="Jean",
            last_name="Dupont",
            is_musician=True,
        )
        d2 = User.objects.create_user(
            username="jean.durand",
            password="pass",
            first_name="Jean",
            last_name="Durand",
            is_musician=True,
        )
        handles2 = assign_mention_handles([d1, d2])
        self.assertEqual(handles2[d1.pk], "Jean Dup")
        self.assertEqual(handles2[d2.pk], "Jean Dur")

        payload = serialize_mention_members([a, b, c])
        by_id = {row["id"]: row for row in payload}
        self.assertEqual(by_id[a.pk]["handle"], "Stéphane G")
        self.assertEqual(by_id[c.pk]["handle"], "Adrien")

        room = ensure_orchestra_room()
        sync_musician_to_orchestra(a)
        sync_musician_to_orchestra(b)
        matched = resolve_mentioned_users(room, "@Stéphane G salut", exclude_user=c)
        self.assertEqual([u.pk for u in matched], [a.pk])

    def test_edit_message_marks_unread(self):
        from django.utils import timezone

        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        sync_musician_to_orchestra(self.other)
        msg = post_message(room=room, author=self.musician, body="Version 1")

        # Destinataire a lu le salon
        membership = ChatMembership.objects.get(room=room, user=self.other)
        membership.last_read_at = timezone.now()
        membership.save(update_fields=["last_read_at"])
        self.assertEqual(unread_count(membership), 0)

        edited = edit_message(message=msg, editor=self.musician, body="Version 2")
        self.assertIsNotNone(edited.edited_at)
        self.assertEqual(edited.body, "Version 2")
        payload = serialize_message(edited)
        self.assertEqual(payload["body"], "Version 2")
        self.assertIsNotNone(payload["edited_at"])

        membership.refresh_from_db()
        self.assertEqual(unread_count(membership), 1)

        # Autrui ne peut pas éditer
        with self.assertRaises(ValueError):
            edit_message(message=msg, editor=self.other, body="Hack")

        client = Client()
        client.login(username="chat_musi", password="pass")
        r = client.post(
            reverse("chat:api_edit", args=[room.pk]),
            {"message_id": msg.pk, "body": "Version 3"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"]["body"], "Version 3")

    def test_read_receipts_via_watermark(self):
        from datetime import timedelta

        from django.utils import timezone

        from chat.services import mark_room_read, room_read_cursors

        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        sync_musician_to_orchestra(self.other)
        msg = post_message(room=room, author=self.musician, body="Bonjour")

        # Personne n’a encore de curseur (sauf si sync a lu — non)
        ChatMembership.objects.filter(room=room).update(last_read_at=None)
        self.assertEqual(room_read_cursors(room), [])

        cursor = mark_room_read(room, self.other, broadcast=True)
        self.assertIsNotNone(cursor)
        self.assertEqual(cursor["user_id"], self.other.pk)
        self.assertTrue(cursor["last_read_at"])

        cursors = room_read_cursors(room)
        self.assertEqual(len(cursors), 1)
        self.assertEqual(cursors[0]["user_id"], self.other.pk)

        # Le destinataire a lu après l’envoi → message couvert
        membership = ChatMembership.objects.get(room=room, user=self.other)
        self.assertIsNotNone(membership.last_read_at)
        self.assertGreaterEqual(membership.last_read_at, msg.created_at)

        client = Client()
        client.login(username="chat_musi", password="pass")
        r = client.get(reverse("chat:room", args=[room.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "chat-reads-")
        self.assertContains(r, "api/read/")

        client.login(username="chat_other", password="pass")
        # Remettre un curseur ancien pour tester l’API
        ChatMembership.objects.filter(room=room, user=self.other).update(
            last_read_at=timezone.now() - timedelta(hours=1)
        )
        r = client.post(reverse("chat:api_read", args=[room.pk]))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["cursor"]["user_id"], self.other.pk)
        membership.refresh_from_db()
        self.assertGreater(
            membership.last_read_at, timezone.now() - timedelta(minutes=1)
        )

    def test_rehearsal_room_gets_setlist_tip_once(self):
        event = Event.objects.create(
            titre="Répé tip",
            type=self.etype,
            venue=self.venue,
            date_debut=timezone.make_aware(timezone.datetime(2030, 7, 1, 20, 15)),
            statut="confirme",
        )
        self.assertTrue(event.is_rehearsal)
        room = ChatRoom.objects.get(event=event)
        tips = ChatMessage.objects.filter(
            room=room,
            kind=ChatMessage.Kind.SYSTEM,
            body__startswith=REHEARSAL_SETLIST_TIP_PREFIX,
        )
        self.assertEqual(tips.count(), 1)
        tip = tips.get()
        # Tip auto : digéré pour les membres déjà présents (pas d’alerte chat).
        for m in ChatMembership.objects.filter(room=room, left_at__isnull=True):
            self.assertGreaterEqual(m.last_digested_message_id, tip.pk)
        self.assertIsNone(ensure_rehearsal_setlist_tip(room))
        self.assertEqual(tips.count(), 1)
        ensure_event_room(event)
        self.assertEqual(tips.count(), 1)

    def test_concert_room_has_no_setlist_tip(self):
        concert_type = EventType.objects.create(nom="Concert", is_rehearsal=False)
        event = Event.objects.create(
            titre="Concert sans tip",
            type=concert_type,
            venue=self.venue,
            date_debut=timezone.make_aware(timezone.datetime(2030, 8, 1, 20, 0)),
            statut="confirme",
        )
        self.assertFalse(event.is_rehearsal)
        room = ChatRoom.objects.get(event=event)
        self.assertFalse(
            ChatMessage.objects.filter(
                room=room,
                kind=ChatMessage.Kind.SYSTEM,
                body__startswith=REHEARSAL_SETLIST_TIP_PREFIX,
            ).exists()
        )
        self.assertIsNone(ensure_rehearsal_setlist_tip(room))


class ChatNotificationDeepLinkTests(TestCase):
    def test_chat_room_url_with_message(self):
        self.assertEqual(chat_room_url(7), reverse("chat:room", args=[7]))
        self.assertEqual(
            chat_room_url(7, message_id=123),
            reverse("chat:room", args=[7]) + "?msg=123",
        )

    @classmethod
    def setUpTestData(cls):
        ensure_participation_statuses()
        cls.venue = Venue.objects.create(nom="Salle Notif", ville="La Roche-sur-Yon")
        cls.etype = EventType.objects.create(nom="Concert")
        cls.musician = User.objects.create_user(
            username="notif_musi",
            password="pass",
            email="notif_musi@example.com",
            is_musician=True,
        )
        cls.other = User.objects.create_user(
            username="notif_other",
            password="pass",
            email="notif_other@example.com",
            is_musician=True,
        )

    def test_mention_notification_links_to_message(self):
        from users.models import UserNotification

        room = ensure_orchestra_room()
        sync_musician_to_orchestra(self.musician)
        sync_musician_to_orchestra(self.other)
        msg = post_message(
            room=room,
            author=self.other,
            body=f"Salut @{self.musician.username}",
        )
        notif = UserNotification.objects.filter(
            user=self.musician,
            related_type="chat_msg",
            related_id=msg.pk,
        ).get()
        self.assertIn(f"?msg={msg.pk}", notif.url)
        self.assertTrue(notif.url.startswith(reverse("chat:room", args=[room.pk])))

    def test_event_invite_links_to_event_room(self):
        from planning.services import notify_event_invite
        from users.models import UserNotification

        event = Event.objects.create(
            titre="Soirée jazz",
            type=self.etype,
            venue=self.venue,
            date_debut=timezone.make_aware(timezone.datetime(2030, 6, 1, 20, 0)),
            statut="confirme",
        )
        room = ChatRoom.objects.get(event=event)
        notify_event_invite(event, [self.musician])
        notif = UserNotification.objects.get(user=self.musician)
        self.assertEqual(notif.url, reverse("chat:room", args=[room.pk]))

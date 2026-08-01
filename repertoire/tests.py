from __future__ import annotations

import io
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from chat.models import ChatMessage, ChatRoom
from chat.services import ensure_piece_room, notify_piece_chorus_update
from planning.models import MusicianProfile
from repertoire.chorus import (
    format_chorus_order,
    parse_chorus_order,
    resolve_solo_selection,
    solo_pool_entries,
)
from repertoire.models import (
    BIG_BAND_POSTES,
    PART_DISPLAY_ORDER,
    Part,
    PartPoste,
    Piece,
    Setlist,
    SetlistItem,
    part_sort_order,
)
from repertoire.pdf_utils import (
    extract_pdf_pages_bytes,
    images_to_pdf_bytes,
    pdf_page_count,
    rotate_pdf_page,
)

User = get_user_model()


def _tiny_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PieceMediaTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="chef", password="x", is_staff=True, is_superuser=True
        )
        self.musician = User.objects.create_user(
            username="tromba", password="x", is_musician=True
        )
        self.piece = Piece.objects.create(
            title="Satin Doll",
            is_published=True,
            youtube_url_1="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            youtube_url_2="https://youtu.be/abc1234",
        )

    def test_youtube_links_helper(self):
        self.assertEqual(len(self.piece.youtube_links()), 2)
        self.piece.youtube_url_3 = "https://www.youtube.com/watch?v=zzzzzzz"
        self.assertEqual(len(self.piece.youtube_links()), 3)

    def test_youtube_videos_helper(self):
        videos = self.piece.youtube_videos()
        self.assertEqual(len(videos), 2)
        self.assertEqual(videos[0]["id"], "dQw4w9WgXcQ")
        self.assertIn("i.ytimg.com/vi/dQw4w9WgXcQ", videos[0]["thumbnail"])
        self.assertEqual(videos[1]["id"], "abc1234")

    def test_detail_shows_youtube(self):
        self.client.login(username="tromba", password="x")
        r = self.client.get(reverse("repertoire:detail", args=[self.piece.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Références YouTube")
        self.assertContains(r, "i.ytimg.com/vi/dQw4w9WgXcQ")
        self.assertContains(r, "rep-yt-card")
        self.assertContains(r, "youtube.com/watch?v=dQw4w9WgXcQ")

    def test_staff_can_upload_audio(self):
        self.client.login(username="chef", password="x")
        audio = SimpleUploadedFile(
            "satin.mp3",
            b"ID3fakeaudio",
            content_type="audio/mpeg",
        )
        r = self.client.post(
            reverse("repertoire:staff_piece_edit", args=[self.piece.slug]),
            {
                "title": self.piece.title,
                "is_published": "on",
                "remarks": "",
                "chorus_order": "",
                "youtube_url_1": self.piece.youtube_url_1,
                "youtube_url_2": self.piece.youtube_url_2,
                "youtube_url_3": "",
                "audio_recording": audio,
            },
        )
        self.assertEqual(r.status_code, 302)
        self.piece.refresh_from_db()
        self.assertTrue(self.piece.audio_recording)
        self.assertIn("satin", self.piece.audio_recording.name)

    def test_piece_salon_chrome_has_audio(self):
        self.piece.audio_recording = SimpleUploadedFile(
            "clean.mp3", b"ID3x", content_type="audio/mpeg"
        )
        self.piece.save()
        room = ensure_piece_room(self.piece)
        self.client.login(username="tromba", password="x")
        r = self.client.get(reverse("chat:room", args=[room.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Enregistrement")
        self.assertContains(r, self.piece.audio_recording.url)
        self.assertContains(r, "YouTube")


class PdfUtilsTests(TestCase):
    def test_images_to_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i in range(2):
                p = Path(tmp) / f"{i}.png"
                p.write_bytes(_tiny_png_bytes())
                paths.append(p)
            data = images_to_pdf_bytes(paths)
            self.assertTrue(data[:4] == b"%PDF" or data.startswith(b"%PDF"))
            out = Path(tmp) / "out.pdf"
            out.write_bytes(data)
            self.assertGreaterEqual(pdf_page_count(out), 1)

    def test_extract_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.png"
            p.write_bytes(_tiny_png_bytes())
            pdf_data = images_to_pdf_bytes([p, p, p])
            src = Path(tmp) / "src.pdf"
            src.write_bytes(pdf_data)
            extracted = extract_pdf_pages_bytes(src, 2, 3)
            out = Path(tmp) / "part.pdf"
            out.write_bytes(extracted)
            self.assertEqual(pdf_page_count(out), 2)


class PieceChatTests(TestCase):
    def setUp(self):
        self.musician = User.objects.create_user(
            username="sax", password="x", is_musician=True
        )
        self.staff = User.objects.create_user(
            username="staff", password="x", is_staff=True
        )
        self.piece = Piece.objects.create(
            title="Take the A Train",
            is_published=True,
            chorus_order="1. Piano  2. Alto 1",
            remarks="Intro 4 mesures",
        )

    def test_ensure_piece_room_seeds_and_system_message(self):
        room = ensure_piece_room(self.piece)
        self.assertEqual(room.kind, ChatRoom.Kind.PIECE)
        self.assertTrue(room.memberships.filter(user=self.musician, left_at__isnull=True).exists())
        self.assertTrue(room.memberships.filter(user=self.staff).exists())
        sys_msg = ChatMessage.objects.filter(room=room, kind=ChatMessage.Kind.SYSTEM).first()
        self.assertIsNotNone(sys_msg)
        self.assertIn("Piano", sys_msg.body)

    def test_chorus_notify(self):
        ensure_piece_room(self.piece)
        self.piece.update_chorus_order("Alto 1 seul")
        msg = notify_piece_chorus_update(self.piece, author=self.staff)
        self.assertIsNotNone(msg)
        self.assertIn("Alto 1", msg.body)


class SetlistTests(TestCase):
    def test_duplicate(self):
        piece = Piece.objects.create(title="Fever", is_published=True)
        sl = Setlist.objects.create(title="Soirée 1")
        SetlistItem.objects.create(setlist=sl, piece=piece, position=1)
        copy = sl.duplicate(title="Soirée 2")
        self.assertEqual(copy.items.count(), 1)
        self.assertEqual(copy.items.first().piece_id, piece.pk)
        self.assertNotEqual(copy.pk, sl.pk)

    def test_sync_items_order_and_notes(self):
        a = Piece.objects.create(title="Alpha", is_published=True)
        b = Piece.objects.create(title="Bravo", is_published=True)
        c = Piece.objects.create(title="Charlie", is_published=True)
        sl = Setlist.objects.create(title="Soirée")
        SetlistItem.objects.create(setlist=sl, piece=a, position=1)
        sl.sync_items([c.pk, a.pk], {c.pk: "ouverture", a.pk: ""})
        items = list(sl.items.order_by("position"))
        self.assertEqual([i.piece_id for i in items], [c.pk, a.pk])
        self.assertEqual(items[0].note, "ouverture")
        self.assertFalse(sl.items.filter(piece=b).exists())

    def test_staff_create_builder_and_save(self):
        staff = User.objects.create_user(
            username="setlist-staff", password="x", is_staff=True
        )
        p1 = Piece.objects.create(title="Take Five", is_published=True)
        p2 = Piece.objects.create(title="Blue Bossa", is_published=True)
        self.client.login(username="setlist-staff", password="x")
        r = self.client.get(reverse("repertoire:staff_setlist_create"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "rep-builder")
        self.assertContains(r, "Take Five")
        self.assertContains(r, "setlistBuilder")
        r2 = self.client.post(
            reverse("repertoire:staff_setlist_create"),
            {
                "title": "Bal du 14",
                "notes": "",
                "is_active": "on",
                "piece_ids": [str(p2.pk), str(p1.pk)],
                f"note_{p2.pk}": "opener",
            },
        )
        self.assertEqual(r2.status_code, 302)
        sl = Setlist.objects.get(title="Bal du 14")
        items = list(sl.items.order_by("position"))
        self.assertEqual([i.piece_id for i in items], [p2.pk, p1.pk])
        self.assertEqual(items[0].note, "opener")

    def test_staff_create_prefills_event(self):
        from datetime import timedelta

        from django.utils import timezone

        from events.models import Event, EventType, Venue

        staff = User.objects.create_user(
            username="setlist-prefill", password="x", is_staff=True
        )
        venue = Venue.objects.create(nom="Salle Prefill", ville="La Roche-sur-Yon")
        et = EventType.objects.create(nom="Concert prefill")
        event = Event.objects.create(
            titre="Gala JOY",
            type=et,
            venue=venue,
            date_debut=timezone.now() + timedelta(days=30),
        )
        self.client.login(username="setlist-prefill", password="x")
        r = self.client.get(
            reverse("repertoire:staff_setlist_create"), {"event": event.pk}
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Gala JOY")
        form = r.context["form"]
        self.assertEqual(form.initial.get("event"), event)
        self.assertEqual(form.initial.get("title"), "Gala JOY")

    def test_staff_attach_setlist_to_event(self):
        from datetime import timedelta

        from django.utils import timezone

        from events.models import Event, EventType, Venue

        staff = User.objects.create_user(
            username="setlist-attach", password="x", is_staff=True
        )
        venue = Venue.objects.create(nom="Salle Attach", ville="La Roche-sur-Yon")
        et = EventType.objects.create(nom="Concert attach")
        event = Event.objects.create(
            titre="Soirée attach",
            type=et,
            venue=venue,
            date_debut=timezone.now() + timedelta(days=40),
        )
        sl = Setlist.objects.create(title="Programme libre")
        self.client.login(username="setlist-attach", password="x")
        r = self.client.post(
            reverse("repertoire:staff_setlist_attach", args=[event.pk]),
            {"setlist_id": sl.pk},
        )
        self.assertEqual(r.status_code, 302)
        sl.refresh_from_db()
        self.assertEqual(sl.event_id, event.pk)
        self.assertTrue(sl.is_active)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class MusicianViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="player", password="x", is_musician=True
        )
        self.piece = Piece.objects.create(title="Route 66", is_published=True)
        Part.objects.create(
            piece=self.piece,
            poste=PartPoste.BASSE,
            file=SimpleUploadedFile("basse.pdf", b"%PDF-1.4\n%", content_type="application/pdf"),
        )

    def test_list_requires_login(self):
        r = self.client.get(reverse("repertoire:list"))
        self.assertEqual(r.status_code, 302)

    def test_list_filter_poste(self):
        self.client.login(username="player", password="x")
        r = self.client.get(reverse("repertoire:list"), {"poste": "basse"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Route 66")
        r2 = self.client.get(reverse("repertoire:list"), {"poste": "alto_1"})
        self.assertEqual(r2.status_code, 200)
        self.assertNotContains(r2, "Route 66")

    def test_pdf_download_vs_inline_preview(self):
        self.client.login(username="player", password="x")
        part = self.piece.parts.get()
        url = reverse("repertoire:part_pdf", args=[part.pk])
        dl = self.client.get(url)
        self.assertEqual(dl.status_code, 200)
        self.assertIn("attachment", dl.get("Content-Disposition", ""))
        preview = self.client.get(url, {"inline": "1"})
        self.assertEqual(preview.status_code, 200)
        self.assertIn("inline", preview.get("Content-Disposition", ""))
        self.assertEqual(preview.get("X-Frame-Options"), "SAMEORIGIN")

class ChorusOrderHelpersTests(TestCase):
    def test_parse_multiline_and_inline(self):
        self.assertEqual(
            parse_chorus_order("1. Piano\n2. 1er alto"),
            ["Piano", "1er alto"],
        )
        self.assertEqual(
            parse_chorus_order("1. Piano  2. Alto 1"),
            ["Piano", "Alto 1"],
        )

    def test_format_roundtrip(self):
        text = format_chorus_order(["Piano", "Basse"])
        self.assertEqual(text, "1. Piano\n2. Basse")
        self.assertEqual(parse_chorus_order(text), ["Piano", "Basse"])

    def test_pool_uses_titulaire_name(self):
        user = User.objects.create_user(
            username="pianiste",
            password="x",
            is_musician=True,
            first_name="Nina",
            last_name="Simone",
        )
        profile = user.musician_profile
        profile.poste_titulaire = MusicianProfile.Poste.PIANO
        profile.save()
        pool = solo_pool_entries()
        piano = next(p for p in pool if p["id"] == f"m{profile.pk}")
        self.assertEqual(piano["poste"], "Piano")
        self.assertIn("Nina", piano["name"])
        self.assertIn("Piano", piano["title"])

    def test_resolve_matches_poste_and_keeps_custom(self):
        pool = [
            {
                "id": "p:piano",
                "name": "",
                "poste": "Piano",
                "title": "Piano",
            },
            {
                "id": "m1",
                "name": "Ada Lovelace",
                "poste": "1er alto",
                "title": "Ada Lovelace — 1er alto",
            },
        ]
        selected = resolve_solo_selection(
            "1. Piano\n2. Guest solo\n3. Ada Lovelace — 1er alto",
            pool,
        )
        self.assertEqual(selected[0]["id"], "p:piano")
        self.assertTrue(selected[1]["id"].startswith("custom-"))
        self.assertEqual(selected[1]["title"], "Guest solo")
        self.assertEqual(selected[2]["id"], "m1")


class SoloBuilderStaffTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="solo-staff", password="x", is_staff=True
        )
        self.musician = User.objects.create_user(
            username="alto1",
            password="x",
            is_musician=True,
            first_name="Charlie",
            last_name="Parker",
        )
        profile = self.musician.musician_profile
        profile.poste_titulaire = MusicianProfile.Poste.ALTO_1
        profile.save()
        self.piece = Piece.objects.create(
            title="Cherokee",
            is_published=True,
            chorus_order="1. Piano",
        )

    def test_edit_form_has_solo_builder(self):
        self.client.login(username="solo-staff", password="x")
        r = self.client.get(
            reverse("repertoire:staff_piece_edit", args=[self.piece.slug])
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "soloBuilder")
        self.assertContains(r, "Ordre des solos")
        self.assertContains(r, "Musiciens / postes")
        self.assertContains(r, "Charlie")
        self.assertEqual(len(r.context["solo_selected"]), 1)
        self.assertEqual(r.context["solo_selected"][0]["title"], "Piano")

    def test_save_chorus_order_from_builder(self):
        self.client.login(username="solo-staff", password="x")
        profile = self.musician.musician_profile
        title = f"Charlie Parker — {profile.get_poste_titulaire_display()}"
        r = self.client.post(
            reverse("repertoire:staff_piece_edit", args=[self.piece.slug]),
            {
                "title": self.piece.title,
                "is_published": "on",
                "remarks": "",
                "chorus_order": f"1. {title}\n2. Piano",
                "youtube_url_1": "",
                "youtube_url_2": "",
                "youtube_url_3": "",
            },
        )
        self.assertEqual(r.status_code, 302)
        self.piece.refresh_from_db()
        self.assertIn("Charlie Parker", self.piece.chorus_order)
        self.assertIn("Piano", self.piece.chorus_order)
        self.assertIsNotNone(self.piece.chorus_order_updated_at)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PdfDecoupeEditorTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="cut-staff", password="x", is_staff=True
        )
        self.piece = Piece.objects.create(title="Foggy Split", is_published=True)
        png = Path(tempfile.mkdtemp()) / "p.png"
        png.write_bytes(_tiny_png_bytes())
        self.pdf_bytes = images_to_pdf_bytes([png, png, png, png])

    def _upload(self):
        self.client.login(username="cut-staff", password="x")
        return self.client.post(
            reverse("repertoire:staff_piece_decoupe_upload", args=[self.piece.slug]),
            {
                "source_pdf": SimpleUploadedFile(
                    "pack.pdf", self.pdf_bytes, content_type="application/pdf"
                )
            },
        )

    def test_upload_and_thumb(self):
        r = self._upload()
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["page_count"], 4)
        thumb = self.client.get(
            reverse(
                "repertoire:staff_piece_decoupe_thumb",
                args=[self.piece.slug, 2],
            )
        )
        self.assertEqual(thumb.status_code, 200)
        self.assertEqual(thumb["Content-Type"], "image/jpeg")
        self.assertTrue(thumb.getvalue()[:3] == b"\xff\xd8\xff")

    def test_commit_contiguous_ranges(self):
        self._upload()
        r = self.client.post(
            reverse("repertoire:staff_piece_decoupe_commit", args=[self.piece.slug]),
            data='{"ranges":[{"poste":"baryton","start":1,"end":2},{"poste":"piano","start":3,"end":4}]}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(self.piece.parts.count(), 2)
        bari = self.piece.parts.get(poste=PartPoste.BARYTON)
        self.assertEqual(pdf_page_count(bari.file.path), 2)
        piano = self.piece.parts.get(poste=PartPoste.PIANO)
        self.assertEqual(pdf_page_count(piano.file.path), 2)

    def test_rotate_page_left_and_right(self):
        import pikepdf

        from repertoire import split_store

        self._upload()
        source = split_store.load_from_session(self.client.session, self.piece.pk)
        self.assertIsNotNone(source)
        # Warm thumb cache then rotate — thumb must be rebuilt
        thumb = self.client.get(
            reverse(
                "repertoire:staff_piece_decoupe_thumb",
                args=[self.piece.slug, 2],
            )
        )
        self.assertEqual(thumb.status_code, 200)
        self.assertTrue(source.thumb_path(2).is_file())

        r = self.client.post(
            reverse(
                "repertoire:staff_piece_decoupe_rotate",
                args=[self.piece.slug, 2],
            ),
            data='{"direction":"right"}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["rotate"] % 360, 90)
        self.assertFalse(source.thumb_path(2).is_file())

        with pikepdf.open(source.pdf_path) as pdf:
            self.assertEqual(int(pdf.pages[1].get("/Rotate", 0) or 0) % 360, 90)

        r2 = self.client.post(
            reverse(
                "repertoire:staff_piece_decoupe_rotate",
                args=[self.piece.slug, 2],
            ),
            data='{"direction":"left"}',
            content_type="application/json",
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["rotate"] % 360, 0)

        # Other pages untouched
        with pikepdf.open(source.pdf_path) as pdf:
            self.assertEqual(int(pdf.pages[0].get("/Rotate", 0) or 0) % 360, 0)
            self.assertEqual(int(pdf.pages[1].get("/Rotate", 0) or 0) % 360, 0)

    def test_concurrent_rotations_are_serialized(self):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch

        import pikepdf

        from repertoire import split_store

        self._upload()
        source = split_store.load_from_session(self.client.session, self.piece.pk)
        self.assertIsNotNone(source)

        real_open = pikepdf.open
        calls_lock = threading.Lock()
        start = threading.Barrier(4)
        active_calls = 0
        max_active_calls = 0

        def slow_open(*args, **kwargs):
            nonlocal active_calls, max_active_calls
            with calls_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            try:
                time.sleep(0.05)
                return real_open(*args, **kwargs)
            finally:
                with calls_lock:
                    active_calls -= 1

        def rotate(page):
            start.wait()
            return rotate_pdf_page(source.pdf_path, page, 90)

        with patch("pikepdf.open", side_effect=slow_open):
            with ThreadPoolExecutor(max_workers=4) as pool:
                angles = list(pool.map(rotate, range(1, 5)))

        self.assertEqual(angles, [90, 90, 90, 90])
        self.assertEqual(max_active_calls, 1)
        with real_open(source.pdf_path) as pdf:
            self.assertEqual(
                [int(page.get("/Rotate", 0) or 0) % 360 for page in pdf.pages],
                [90, 90, 90, 90],
            )

    def test_reject_overlap_and_duplicate_poste(self):
        self._upload()
        r = self.client.post(
            reverse("repertoire:staff_piece_decoupe_commit", args=[self.piece.slug]),
            data='{"ranges":[{"poste":"basse","start":1,"end":3},{"poste":"piano","start":2,"end":4}]}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])
        r2 = self.client.post(
            reverse("repertoire:staff_piece_decoupe_commit", args=[self.piece.slug]),
            data='{"ranges":[{"poste":"basse","start":1,"end":1},{"poste":"basse","start":2,"end":2}]}',
            content_type="application/json",
        )
        self.assertEqual(r2.status_code, 400)

    def test_editor_page_and_atelier_link(self):
        self.client.login(username="cut-staff", password="x")
        r = self.client.get(
            reverse("repertoire:staff_piece_decoupe", args=[self.piece.slug])
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "pdfSplitEditor")
        edit = self.client.get(
            reverse("repertoire:staff_piece_edit", args=[self.piece.slug])
        )
        self.assertContains(edit, "Ouvrir la découpe")
        self.assertContains(
            edit, reverse("repertoire:staff_piece_decoupe", args=[self.piece.slug])
        )



    def test_load_from_server_inbox(self):
        from django.conf import settings

        from repertoire import split_store

        inbox = Path(settings.MEDIA_ROOT) / "repertoire" / "_inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        # Extensionless PDF named like the piece (as in prod inbox)
        server_pdf = inbox / "Foggy_Split_full"
        server_pdf.write_bytes(self.pdf_bytes)
        self.assertTrue(server_pdf.read_bytes()[:5] == b"%PDF-")

        cands = split_store.list_server_candidates(
            title=self.piece.title, slug=self.piece.slug
        )
        self.assertTrue(cands, "expected inbox candidate")
        cid = cands[0].id

        self.client.login(username="cut-staff", password="x")
        page = self.client.get(
            reverse("repertoire:staff_piece_decoupe", args=[self.piece.slug])
        )
        self.assertContains(page, "Sur le serveur")
        self.assertContains(page, "Foggy_Split_full")

        r = self.client.post(
            reverse(
                "repertoire:staff_piece_decoupe_from_server", args=[self.piece.slug]
            ),
            data=f'{{"id":"{cid}"}}',
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["page_count"], 4)


class MissingBigBandPartsTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="atelier-alert", password="x", is_staff=True
        )
        self.piece = Piece.objects.create(title="Splanky Incomplete", is_published=True)
        Part.objects.create(
            piece=self.piece,
            poste=PartPoste.BASSE,
            file=SimpleUploadedFile(
                "basse.pdf", b"%PDF-1.4\n%", content_type="application/pdf"
            ),
        )

    def test_missing_excludes_optional_postes(self):
        missing = self.piece.missing_big_band_postes()
        self.assertEqual(len(missing), len(BIG_BAND_POSTES) - 1)
        self.assertNotIn(PartPoste.BASSE, missing)
        self.assertNotIn(PartPoste.CLARINETTE, missing)
        self.assertNotIn(PartPoste.CHANT, missing)
        self.assertNotIn(PartPoste.CONDUCTEUR, missing)
        self.assertIn(PartPoste.ALTO_1, missing)
        self.assertIn("1er alto", self.piece.missing_big_band_labels())

    def test_staff_list_shows_alert_dot(self):
        self.client.login(username="atelier-alert", password="x")
        r = self.client.get(reverse("repertoire:staff_list"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="rep-alert-dot"')
        self.assertContains(r, "postes manquants")

    def test_complete_piece_has_no_alert(self):
        for poste in BIG_BAND_POSTES:
            if poste == PartPoste.BASSE:
                continue
            Part.objects.create(
                piece=self.piece,
                poste=poste,
                file=SimpleUploadedFile(
                    f"{poste}.pdf", b"%PDF-1.4\n%", content_type="application/pdf"
                ),
            )
        self.assertEqual(self.piece.missing_big_band_postes(), [])
        self.client.login(username="atelier-alert", password="x")
        r = self.client.get(reverse("repertoire:staff_list"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'class="rep-alert-dot"')
        self.assertNotContains(r, "postes manquants")
        self.assertNotContains(r, "poste manquant")
    def test_edit_page_lists_missing_postes(self):
        self.client.login(username="atelier-alert", password="x")
        r = self.client.get(
            reverse("repertoire:staff_piece_edit", args=[self.piece.slug])
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "rep-missing-alert")
        self.assertContains(r, "1er alto")
        self.assertContains(r, "sans partition")

    def test_musician_list_shows_alert_dot(self):
        musician = User.objects.create_user(
            username="alert-player", password="x", is_musician=True
        )
        self.client.login(username="alert-player", password="x")
        r = self.client.get(reverse("repertoire:list"), {"poste": "all"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Splanky Incomplete")
        self.assertContains(r, 'class="rep-alert-dot"')
        self.assertContains(r, "postes manquants")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PartDisplayOrderTests(TestCase):
    def test_display_order_starts_with_conducteur_then_chant(self):
        self.assertEqual(PART_DISPLAY_ORDER[0], PartPoste.CONDUCTEUR)
        self.assertEqual(PART_DISPLAY_ORDER[1], PartPoste.CHANT)
        self.assertLess(
            part_sort_order(PartPoste.BARYTON),
            part_sort_order(PartPoste.TROMPETTE_1),
        )
        self.assertLess(
            part_sort_order(PartPoste.TROMPETTE_4),
            part_sort_order(PartPoste.TROMBONE_1),
        )
        self.assertLess(
            part_sort_order(PartPoste.TROMBONE_4),
            part_sort_order(PartPoste.PIANO),
        )

    def test_parts_queryset_follows_family_order(self):
        piece = Piece.objects.create(title="Ordered Parts", is_published=True)
        pdf = lambda name: SimpleUploadedFile(
            name, b"%PDF-1.4\n%", content_type="application/pdf"
        )
        for poste in (
            PartPoste.BATTERIE,
            PartPoste.TROMPETTE_1,
            PartPoste.CHANT,
            PartPoste.CONDUCTEUR,
            PartPoste.ALTO_1,
            PartPoste.TROMBONE_1,
            PartPoste.PIANO,
        ):
            Part.objects.create(piece=piece, poste=poste, file=pdf(f"{poste}.pdf"))

        ordered = list(piece.parts.values_list("poste", flat=True))
        self.assertEqual(
            ordered,
            [
                PartPoste.CONDUCTEUR,
                PartPoste.CHANT,
                PartPoste.ALTO_1,
                PartPoste.TROMPETTE_1,
                PartPoste.TROMBONE_1,
                PartPoste.PIANO,
                PartPoste.BATTERIE,
            ],
        )

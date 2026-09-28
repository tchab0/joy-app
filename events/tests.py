from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from core.models import EvenementMedia, MediaItem
from events.models import Event, EventType, Organisme, Venue
from events.organisme import organisme_url_for_name, remember_organisme

User = get_user_model()


class OrganismeUrlTests(TestCase):
    def test_remember_organisme_stores_url(self):
        remember_organisme("Mairie de La Roche-sur-Yon", "https://larochesuryon.fr")
        obj = Organisme.objects.get(nom="Mairie de La Roche-sur-Yon")
        self.assertEqual(obj.url_site, "https://larochesuryon.fr")

    def test_remember_organisme_updates_existing_url(self):
        Organisme.objects.create(nom="Festival JOY", url_site="https://old.example")
        remember_organisme("Festival JOY", "https://joy.example")
        self.assertEqual(
            Organisme.objects.get(nom="Festival JOY").url_site,
            "https://joy.example",
        )

    def test_organisme_url_for_name_case_insensitive(self):
        Organisme.objects.create(nom="Mairie Test", url_site="https://mairie.test")
        self.assertEqual(organisme_url_for_name("mairie test"), "https://mairie.test")

    def test_event_organisme_url_property(self):
        venue = Venue.objects.create(nom="Salle", ville="Ville")
        event_type = EventType.objects.create(nom="Concert")
        Organisme.objects.create(nom="Asso Jazz", url_site="https://jazz.test")
        event = Event.objects.create(
            titre="Concert test",
            type=event_type,
            venue=venue,
            date_debut=timezone.now() + timedelta(days=1),
            organisme="Asso Jazz",
            public=True,
        )
        self.assertEqual(event.organisme_url, "https://jazz.test")


class OrganismePublicDisplayTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(nom="Salle", ville="La Roche-sur-Yon")
        self.event_type = EventType.objects.create(nom="Concert")
        Organisme.objects.create(
            nom="Mairie de La Roche-sur-Yon",
            url_site="https://larochesuryon.fr",
        )
        self.event = Event.objects.create(
            titre="Concert municipal",
            slug="concert-municipal",
            type=self.event_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=10),
            organisme="Mairie de La Roche-sur-Yon",
            public=True,
        )

    def test_public_detail_links_organisme(self):
        r = self.client.get(reverse("concert_detail", args=[self.event.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'href="https://larochesuryon.fr"')
        self.assertContains(r, "Mairie de La Roche-sur-Yon")

    def test_publication_form_saves_organisme_url(self):
        staff = User.objects.create_user(
            username="staff_org",
            password="pass12345",
            is_staff=True,
            is_musician=True,
        )
        event = Event.objects.create(
            titre="Autre concert",
            type=self.event_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=5),
        )
        self.client.login(username="staff_org", password="pass12345")
        r = self.client.post(
            reverse("planning:event_publication", args=[event.pk]),
            {
                "organisme": "Nouvel organisme",
                "organisme_url": "https://nouvel-org.test",
                "parent_mode": "none",
            },
        )
        self.assertEqual(r.status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.organisme, "Nouvel organisme")
        self.assertEqual(
            Organisme.objects.get(nom="Nouvel organisme").url_site,
            "https://nouvel-org.test",
        )


class PastConcertMediaTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(
            nom="Le Stella",
            ville="Les Sables-d'Olonne",
            latitude="46.503718",
            longitude="-1.796830",
        )
        self.event_type = EventType.objects.create(nom="Concert")
        self.past = Event.objects.create(
            titre="Groove Circle",
            type=self.event_type,
            venue=self.venue,
            date_debut=timezone.now() - timedelta(days=8),
            public=True,
        )
        self.media_event = EvenementMedia.objects.create(
            nom="Groove Circle - Les Sables-d'Olonne",
            date=timezone.localtime(self.past.date_debut).date(),
        )

    def _photo(self, *, titre="Photo du concert", publie=True, evenement=None):
        return MediaItem.objects.create(
            type="photo",
            titre=titre,
            fichier=SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff\xd9", content_type="image/jpeg"),
            evenement=evenement if evenement is not None else self.media_event,
            publie=publie,
            statut="publie" if publie else "en_attente",
        )

    def test_past_concert_shows_own_media_under_map(self):
        self._photo()
        r = self.client.get(reverse("concert_detail", args=[self.past.slug]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertLess(html.find('id="event-map-'), html.find('class="event-medias"'))
        self.assertContains(r, "Photo du concert")
        self.assertContains(r, "Voir dans la galerie")
        self.assertContains(r, f"evenement={self.media_event.pk}")

    def test_past_concert_without_media_hides_block(self):
        r = self.client.get(reverse("concert_detail", args=[self.past.slug]))
        self.assertNotContains(r, "event-medias")

    def test_unpublished_media_stays_hidden(self):
        self._photo(publie=False, titre="Brouillon")
        r = self.client.get(reverse("concert_detail", args=[self.past.slug]))
        self.assertNotContains(r, "event-medias")
        self.assertNotContains(r, "Brouillon")

    def test_upcoming_concert_hides_media(self):
        upcoming = Event.objects.create(
            titre="Groove Circle",
            type=self.event_type,
            venue=self.venue,
            date_debut=timezone.now() + timedelta(days=10),
            public=True,
        )
        EvenementMedia.objects.create(
            nom="Groove Circle",
            date=timezone.localtime(upcoming.date_debut).date(),
        )
        self._photo(titre="Trop tôt", evenement=EvenementMedia.objects.get(nom="Groove Circle"))
        r = self.client.get(reverse("concert_detail", args=[upcoming.slug]))
        self.assertNotContains(r, "event-medias")
        self.assertNotContains(r, "Trop tôt")

    def test_lookup_does_not_create_media_event(self):
        from core.media_events import find_evenement_media_for_event

        other = Event.objects.create(
            titre="Café de La Loüv",
            type=self.event_type,
            venue=self.venue,
            date_debut=timezone.now() - timedelta(days=30),
            public=True,
        )
        before = EvenementMedia.objects.count()
        self.assertIsNone(find_evenement_media_for_event(other))
        self.assertEqual(EvenementMedia.objects.count(), before)
        r = self.client.get(reverse("concert_detail", args=[other.slug]))
        self.assertNotContains(r, "event-medias")
        self.assertEqual(EvenementMedia.objects.count(), before)

    def test_concert_type_filter_and_sort_controls(self):
        self._photo()
        MediaItem.objects.create(
            type="video",
            titre="Vidéo du concert",
            fichier=SimpleUploadedFile("c.mp4", b"fake", content_type="video/mp4"),
            evenement=self.media_event,
            publie=True,
            statut="publie",
        )
        r = self.client.get(
            reverse("concert_detail", args=[self.past.slug]),
            {"tri": "types", "type": "video"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Par type")
        self.assertContains(r, "Par événement")
        self.assertContains(r, 'id="media-type"')
        self.assertContains(r, "Vidéo du concert")
        self.assertNotContains(r, "Photo du concert")
        self.assertContains(r, "tri=types")
        self.assertContains(r, "type=video")
        self.assertContains(r, f"evenement={self.media_event.pk}")

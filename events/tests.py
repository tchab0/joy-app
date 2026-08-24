from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

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

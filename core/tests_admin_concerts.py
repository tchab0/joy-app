from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventType, Venue
from django.contrib.auth import get_user_model

User = get_user_model()


class AdminConcertsCmsTests(TestCase):
    def setUp(self):
        self.venue = Venue.objects.create(nom="Salle Test", ville="La Roche-sur-Yon")
        self.concert_type = EventType.objects.create(nom="Concert", is_rehearsal=False)
        self.rep_type = EventType.objects.create(nom="Répétition", is_rehearsal=True)
        self.staff = User.objects.create_user(
            username="cms_staff",
            password="pass12345",
            is_staff=True,
        )
        now = timezone.now()
        self.concert = Event.objects.create(
            titre="Concert à venir",
            type=self.concert_type,
            venue=self.venue,
            date_debut=now + timedelta(days=7),
            public=False,
        )
        self.past_concert = Event.objects.create(
            titre="Concert passé",
            type=self.concert_type,
            venue=self.venue,
            date_debut=now - timedelta(days=30),
            public=True,
        )
        self.rep = Event.objects.create(
            titre="Répétition à venir",
            type=self.rep_type,
            venue=self.venue,
            date_debut=now + timedelta(days=3),
        )

    def test_list_links_concert_title_to_detail(self):
        self.client.login(username="cms_staff", password="pass12345")
        r = self.client.get(reverse("admin_concerts"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse("admin_concert_detail", args=[self.concert.pk]))
        self.assertNotContains(r, self.rep.titre)

    def test_upcoming_detail_shows_edit_for_staff(self):
        self.client.login(username="cms_staff", password="pass12345")
        r = self.client.get(reverse("admin_concert_detail", args=[self.concert.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Modifier")
        self.assertContains(r, reverse("admin_concert_edit", args=[self.concert.pk]))

    def test_past_detail_hides_edit(self):
        self.client.login(username="cms_staff", password="pass12345")
        r = self.client.get(reverse("admin_concert_detail", args=[self.past_concert.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, reverse("admin_concert_edit", args=[self.past_concert.pk]))

    def test_rehearsal_admin_detail_redirects_to_repetitions(self):
        self.client.login(username="cms_staff", password="pass12345")
        r = self.client.get(reverse("admin_concert_detail", args=[self.rep.pk]))
        self.assertRedirects(r, reverse("repetitions:detail", args=[self.rep.pk]))

    def test_repetitions_list_links_to_detail(self):
        self.client.login(username="cms_staff", password="pass12345")
        r = self.client.get(reverse("admin_repetitions"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse("repetitions:detail", args=[self.rep.pk]))

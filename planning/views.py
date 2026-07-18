from collections import defaultdict
from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import TemplateView

from events.models import Event


class PlanningUpcomingView(LoginRequiredMixin, TemplateView):
    template_name = "planning/upcoming_12_months.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        now = timezone.now()
        end_date = now + timedelta(days=365)

        events = (
            Event.objects.filter(date_debut__gte=now, date_debut__lte=end_date)
            .select_related("type", "venue")
            .prefetch_related("participations__user", "participations__status")
            .order_by("date_debut", "titre")
        )

        grouped_events = defaultdict(list)
        for event in events:
            month_key = event.date_debut.strftime("%Y-%m")
            grouped_events[month_key].append(event)

        context["grouped_events"] = dict(grouped_events)
        return context

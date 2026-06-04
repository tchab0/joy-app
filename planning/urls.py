from django.urls import path
from .views import PlanningUpcomingView

app_name = "planning"

urlpatterns = [
    path("concerts/12-mois/", PlanningUpcomingView.as_view(), name="upcoming_12_months"),
]

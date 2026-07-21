from django.urls import path

from core.views import concert_detail

urlpatterns = [
    path("<slug:slug>/", concert_detail, name="concert_detail"),
]

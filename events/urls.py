from django.urls import path

from core.views import concert_detail
from events.views import concert_og_image, concert_share_track

urlpatterns = [
    path("<slug:slug>/og.jpg", concert_og_image, name="concert_og_image"),
    path("<slug:slug>/share/", concert_share_track, name="concert_share_track"),
    path("<slug:slug>/", concert_detail, name="concert_detail"),
]

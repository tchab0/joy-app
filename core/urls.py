from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("concerts/", views.concerts, name="concerts"),
    path("goodies/", views.goodies, name="goodies"),
    path("medias/", views.medias, name="medias"),
    path("don/", views.don, name="don"),
    path("adhesion/", views.adhesion, name="adhesion"),
    path("contact/", views.contact, name="contact"),
]

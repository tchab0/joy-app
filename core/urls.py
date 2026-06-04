from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("concerts/", views.concerts, name="concerts"),
    path("goodies/", views.goodies, name="goodies"),
    path("medias/", views.medias, name="medias"),
    path("medias/proposer/", views.proposer_media, name="proposer_media"),
    path("medias/<int:pk>/vote/", views.media_vote, name="media_vote"),
    path("don/", views.don, name="don"),
    path("adhesion/", views.adhesion, name="adhesion"),
    path("contact/", views.contact, name="contact"),
    path("admin-medias/", views.admin_medias, name="admin_medias"),
    path("admin-contact/", views.admin_contact, name="admin_contact"),
    path("admin-medias/<int:pk>/action/", views.admin_media_action, name="admin_media_action"),
    path('admin-concerts/', views.admin_concerts, name='admin_concerts'),
    path('admin-concerts/ajouter/', views.admin_concert_edit, name='admin_concert_add'),
    path('admin-concerts/<int:pk>/modifier/', views.admin_concert_edit, name='admin_concert_edit'),
    path('admin-concerts/<int:pk>/supprimer/', views.admin_concert_delete, name='admin_concert_delete'),
    path('admin-lieux/', views.admin_venues, name='admin_venues'),
    path('admin-lieux/ajouter/', views.admin_venue_edit, name='admin_venue_add'),
    path('admin-lieux/<int:pk>/modifier/', views.admin_venue_edit, name='admin_venue_edit'),
]
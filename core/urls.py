from django.urls import path
from . import views
from . import page_views

urlpatterns = [
    path("", views.home, name="home"),
    path("concerts/", views.concerts, name="concerts"),
    path("goodies/", views.goodies, name="goodies"),
    path("medias/", views.medias, name="medias"),
    path("medias/proposer/", views.proposer_media, name="proposer_media"),
    path("medias/<int:pk>/vote/", views.media_vote, name="media_vote"),
    path("don/", views.don, name="don"),
    path("adhesion/", views.adhesion, name="adhesion"),
    path("mentions-legales/", views.mentions_legales, name="mentions_legales"),
    path("contact/", views.contact, name="contact"),
    path("admin-medias/", views.admin_medias, name="admin_medias"),
    path("admin-contact/", views.admin_contact, name="admin_contact"),
    path("admin-contact/<int:pk>/supprimer/", views.admin_contact_delete, name="admin_contact_delete"),
    path(
        "admin-notifications/",
        views.admin_notifications,
        name="admin_notifications",
    ),
    path(
        "admin-notifications/<int:pk>/supprimer/",
        views.admin_notification_delete,
        name="admin_notification_delete",
    ),
    path("admin-medias/<int:pk>/action/", views.admin_media_action, name="admin_media_action"),
    path("admin-medias/<int:pk>/editer/", views.admin_media_edit, name="admin_media_edit"),
    path("administration/", views.admin_hub, name="admin_hub"),
    path('admin-concerts/', views.admin_concerts, name='admin_concerts'),
    path('admin-concerts/ajouter/', views.admin_concert_edit, name='admin_concert_add'),
    path('admin-concerts/<int:pk>/modifier/', views.admin_concert_edit, name='admin_concert_edit'),
    path('admin-concerts/<int:pk>/supprimer/', views.admin_concert_delete, name='admin_concert_delete'),
    path('admin-lieux/', views.admin_venues, name='admin_venues'),
    path('admin-lieux/ajouter/', views.admin_venue_edit, name='admin_venue_add'),
    path('admin-lieux/<int:pk>/modifier/', views.admin_venue_edit, name='admin_venue_edit'),
    path("admin-pages/", page_views.admin_pages, name="admin_pages"),
    path("admin-pages/medias/", page_views.admin_page_media_picker, name="admin_page_media_picker"),
    path("admin-pages/<slug:slug>/", page_views.admin_page_edit, name="admin_page_edit"),
    path(
        "admin-pages/<slug:slug>/blocks/",
        page_views.admin_page_block_create,
        name="admin_page_block_create",
    ),
    path(
        "admin-pages/<slug:slug>/blocks/<int:pk>/",
        page_views.admin_page_block_update,
        name="admin_page_block_update",
    ),
    path(
        "admin-pages/<slug:slug>/blocks/<int:pk>/supprimer/",
        page_views.admin_page_block_delete,
        name="admin_page_block_delete",
    ),
    path(
        "admin-pages/<slug:slug>/reorder/",
        page_views.admin_page_reorder,
        name="admin_page_reorder",
    ),
    path(
        "admin-pages/<slug:slug>/upload/",
        page_views.admin_page_upload,
        name="admin_page_upload",
    ),
]
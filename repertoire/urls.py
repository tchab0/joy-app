from django.urls import path

from repertoire import views

app_name = "repertoire"

urlpatterns = [
    path("", views.PieceListView.as_view(), name="list"),
    path("morceau/<slug:slug>/", views.PieceDetailView.as_view(), name="detail"),
    path(
        "morceau/<slug:slug>/salon/",
        views.CreatePieceSalonView.as_view(),
        name="create_salon",
    ),
    path("partition/<int:pk>/", views.PartDownloadView.as_view(), name="part_pdf"),
    # Staff
    path("staff/", views.StaffPieceListView.as_view(), name="staff_list"),
    path("staff/nouveau/", views.StaffPieceCreateView.as_view(), name="staff_piece_create"),
    path(
        "staff/morceau/<slug:slug>/",
        views.StaffPieceEditView.as_view(),
        name="staff_piece_edit",
    ),
    path(
        "staff/morceau/<slug:slug>/upload/",
        views.StaffPartUploadView.as_view(),
        name="staff_part_upload",
    ),
    path(
        "staff/morceau/<slug:slug>/images/",
        views.StaffPartImagesView.as_view(),
        name="staff_part_images",
    ),
    path(
        "staff/morceau/<slug:slug>/split/",
        views.StaffPartSplitView.as_view(),
        name="staff_part_split",
    ),
    path(
        "staff/partition/<int:pk>/supprimer/",
        views.StaffPartDeleteView.as_view(),
        name="staff_part_delete",
    ),
    path("staff/setlists/", views.StaffSetlistListView.as_view(), name="staff_setlist_list"),
    path(
        "staff/setlists/nouvelle/",
        views.StaffSetlistCreateView.as_view(),
        name="staff_setlist_create",
    ),
    path(
        "staff/setlists/<int:pk>/",
        views.StaffSetlistEditView.as_view(),
        name="staff_setlist_edit",
    ),
    path(
        "staff/setlists/<int:pk>/dupliquer/",
        views.StaffSetlistDuplicateView.as_view(),
        name="staff_setlist_duplicate",
    ),
]

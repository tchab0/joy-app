from django.urls import path

from repertoire import split_views, views

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
    path(
        "morceau/<slug:slug>/audio/",
        views.PieceAudioDownloadView.as_view(),
        name="piece_audio",
    ),
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
        "staff/morceau/<slug:slug>/decoupe/",
        split_views.StaffPieceDecoupeView.as_view(),
        name="staff_piece_decoupe",
    ),
    path(
        "staff/morceau/<slug:slug>/decoupe/upload/",
        split_views.StaffPieceDecoupeUploadView.as_view(),
        name="staff_piece_decoupe_upload",
    ),
    path(
        "staff/morceau/<slug:slug>/decoupe/from-server/",
        split_views.StaffPieceDecoupeFromServerView.as_view(),
        name="staff_piece_decoupe_from_server",
    ),
    path(
        "staff/morceau/<slug:slug>/decoupe/page/<int:page>/",
        split_views.StaffPieceDecoupeThumbView.as_view(),
        name="staff_piece_decoupe_thumb",
    ),
    path(
        "staff/morceau/<slug:slug>/decoupe/preview/<int:page>/",
        split_views.StaffPieceDecoupePreviewView.as_view(),
        name="staff_piece_decoupe_preview",
    ),
    path(
        "staff/morceau/<slug:slug>/decoupe/page/<int:page>/rotate/",
        split_views.StaffPieceDecoupeRotateView.as_view(),
        name="staff_piece_decoupe_rotate",
    ),
    path(
        "staff/morceau/<slug:slug>/decoupe/commit/",
        split_views.StaffPieceDecoupeCommitView.as_view(),
        name="staff_piece_decoupe_commit",
    ),
    path(
        "staff/morceau/<slug:slug>/decoupe/clear/",
        split_views.StaffPieceDecoupeClearView.as_view(),
        name="staff_piece_decoupe_clear",
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
        "staff/setlists/lier/<int:event_id>/",
        views.StaffSetlistAttachView.as_view(),
        name="staff_setlist_attach",
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

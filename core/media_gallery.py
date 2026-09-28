"""Tri et filtres partagés pour la galerie /medias/ et les fiches concert."""

from __future__ import annotations

from django.db.models import Count, Exists, F, OuterRef

from core.models import EvenementMedia, MediaItem, MediaVote

TRI_EVENEMENTS = "evenements"
TRI_TYPES = "types"
TRI_VOTES = "votes"
TRI_CHOICES = (TRI_EVENEMENTS, TRI_TYPES, TRI_VOTES)

TYPE_CHOICES = ("photo", "video", "audio", "pdf")
TYPE_LABELS = {
    "photo": "Photos",
    "video": "Vidéos",
    "audio": "Audio",
    "pdf": "Documents",
}


def parse_media_query(get) -> tuple[str, str, str]:
    """Retourne (tri, type_filtre, evenement_raw)."""
    tri = (get.get("tri") or TRI_EVENEMENTS).strip().lower()
    if tri not in TRI_CHOICES:
        tri = TRI_EVENEMENTS
    type_filtre = (get.get("type") or "").strip().lower()
    if type_filtre not in TYPE_CHOICES:
        type_filtre = ""
    evenement_raw = (get.get("evenement") or "").strip()
    return tri, type_filtre, evenement_raw


def annotate_votes(qs, session_key: str):
    return qs.annotate(
        nb_votes=Count("votes"),
        user_a_vote=Exists(
            MediaVote.objects.filter(media=OuterRef("pk"), session_key=session_key)
        ),
    )


def _prepare_item(item: MediaItem) -> MediaItem:
    item.display_url = item.url_affichage
    item.thumb_url = item.url_miniature
    return item


def gallery_events_queryset(evenement_scope: EvenementMedia | None = None):
    """Événements ayant au moins un média publié (tous types)."""
    qs = EvenementMedia.objects.filter(items__publie=True)
    if evenement_scope is not None:
        qs = qs.filter(pk=evenement_scope.pk)
    return qs.distinct().order_by(F("date").desc(nulls_last=True), "nom", "pk")


def empty_type_buckets() -> dict:
    return {"photos": [], "videos": [], "audios": [], "pdfs": []}


def _bucket_key(media_type: str) -> str | None:
    return {
        "photo": "photos",
        "video": "videos",
        "audio": "audios",
        "pdf": "pdfs",
    }.get(media_type)


def build_media_gallery(
    *,
    session_key: str,
    tri: str,
    type_filtre: str = "",
    evenement_raw: str = "",
    evenement_scope: EvenementMedia | None = None,
) -> dict:
    """
    Construit le contexte de galerie.

    - Photos : uniquement rattachées à un événement (orphelines exclues).
    - Vidéos / audio / PDF : publiés, avec ou sans événement (sauf filtre événement).
    - ``evenement_scope`` : restreint à un EvenementMedia (fiche concert).
    """
    evenements_filtre = list(gallery_events_queryset(evenement_scope))

    evenement_actif = None
    if evenement_raw.isdigit():
        evenement_id = int(evenement_raw)
        evenement_actif = next(
            (ev for ev in evenements_filtre if ev.pk == evenement_id), None
        )
    if evenement_scope is not None and evenement_actif is None and not evenement_raw:
        # Fiche concert : l’événement courant est le filtre par défaut.
        evenement_actif = evenement_scope

    base = annotate_votes(
        MediaItem.objects.filter(publie=True).select_related("evenement"),
        session_key,
    )
    if evenement_scope is not None:
        base = base.filter(evenement_id=evenement_scope.pk)

    photos_qs = base.filter(type="photo", evenement__isnull=False)
    videos_qs = base.filter(type="video")
    audios_qs = base.filter(type="audio")
    pdfs_qs = base.filter(type="pdf")

    if evenement_actif is not None:
        photos_qs = photos_qs.filter(evenement_id=evenement_actif.pk)
        videos_qs = videos_qs.filter(evenement_id=evenement_actif.pk)
        audios_qs = audios_qs.filter(evenement_id=evenement_actif.pk)
        pdfs_qs = pdfs_qs.filter(evenement_id=evenement_actif.pk)

    if type_filtre == "photo":
        videos_qs = videos_qs.none()
        audios_qs = audios_qs.none()
        pdfs_qs = pdfs_qs.none()
    elif type_filtre == "video":
        photos_qs = photos_qs.none()
        audios_qs = audios_qs.none()
        pdfs_qs = pdfs_qs.none()
    elif type_filtre == "audio":
        photos_qs = photos_qs.none()
        videos_qs = videos_qs.none()
        pdfs_qs = pdfs_qs.none()
    elif type_filtre == "pdf":
        photos_qs = photos_qs.none()
        videos_qs = videos_qs.none()
        audios_qs = audios_qs.none()

    photos_votes: list[MediaItem] = []
    groupes: list[dict] = []
    videos: list[MediaItem] = []
    photos: list[MediaItem] = []
    audios: list[MediaItem] = []
    pdfs: list[MediaItem] = []

    if tri == TRI_VOTES:
        # Classement photo uniquement ; les autres types restent filtrés mais hors vue votes.
        photos_votes = [
            _prepare_item(p)
            for p in photos_qs.order_by(
                "-nb_votes", "-evenement__date", "evenement_id", "id"
            )
        ]
    elif tri == TRI_TYPES:
        videos = [
            _prepare_item(v)
            for v in videos_qs.order_by(
                F("evenement__date").desc(nulls_last=True), "ordre", "id"
            )
        ]
        photos = [
            _prepare_item(p)
            for p in photos_qs.order_by(
                F("evenement__date").desc(nulls_last=True),
                "evenement_id",
                "ordre",
                "id",
            )
        ]
        audios = [
            _prepare_item(a)
            for a in audios_qs.order_by(
                F("evenement__date").desc(nulls_last=True), "ordre", "id"
            )
        ]
        pdfs = [
            _prepare_item(p)
            for p in pdfs_qs.order_by(
                F("evenement__date").desc(nulls_last=True), "ordre", "id"
            )
        ]
    else:
        # Par événement : un bloc par événement (récent → ancien).
        items: list[MediaItem] = []
        for qs in (
            photos_qs.order_by(
                F("evenement__date").desc(nulls_last=True),
                "evenement_id",
                "ordre",
                "id",
            ),
            videos_qs.order_by(
                F("evenement__date").desc(nulls_last=True),
                "evenement_id",
                "ordre",
                "id",
            ),
            audios_qs.order_by(
                F("evenement__date").desc(nulls_last=True),
                "evenement_id",
                "ordre",
                "id",
            ),
            pdfs_qs.order_by(
                F("evenement__date").desc(nulls_last=True),
                "evenement_id",
                "ordre",
                "id",
            ),
        ):
            items.extend(list(qs))

        groupes_map: dict = {}
        orphelins = empty_type_buckets()
        has_orphans = False
        for item in items:
            _prepare_item(item)
            key = item.evenement_id
            bucket = _bucket_key(item.type)
            if bucket is None:
                continue
            if key is None:
                orphelins[bucket].append(item)
                has_orphans = True
                continue
            if key not in groupes_map:
                groupes_map[key] = {
                    "evenement": item.evenement,
                    **empty_type_buckets(),
                }
            groupes_map[key][bucket].append(item)

        order_ids = [ev.pk for ev in evenements_filtre]
        if evenement_actif is not None:
            order_ids = [evenement_actif.pk]
        seen: set[int] = set()
        for pk in order_ids:
            if pk in groupes_map and pk not in seen:
                groupes.append(groupes_map[pk])
                seen.add(pk)
        for pk, groupe in groupes_map.items():
            if pk not in seen:
                groupes.append(groupe)
                seen.add(pk)
        if has_orphans and evenement_actif is None:
            groupes.append({"evenement": None, **orphelins})

        for g in groupes:
            photos.extend(g["photos"])
            videos.extend(g["videos"])
            audios.extend(g["audios"])
            pdfs.extend(g["pdfs"])

    has_any = bool(photos or videos or audios or pdfs or photos_votes or groupes)

    return {
        "tri": tri,
        "type_filtre": type_filtre,
        "type_labels": TYPE_LABELS,
        "evenements_filtre": evenements_filtre,
        "evenement_actif": evenement_actif,
        "groupes": groupes,
        "groupes_photos": [
            {"evenement": g["evenement"], "photos": g["photos"]}
            for g in groupes
            if g.get("photos")
        ],
        "photos_votes": photos_votes,
        "videos": videos,
        "photos": photos,
        "audios": audios,
        "pdfs": pdfs,
        "has_any_media": has_any,
        "show_diaporama": bool(photos_votes or photos or any(g.get("photos") for g in groupes)),
    }


def gallery_querystring(
    *,
    tri: str,
    type_filtre: str = "",
    evenement_actif: EvenementMedia | None = None,
) -> str:
    """Query string relative pour liens de contrôles / « Voir dans la galerie »."""
    parts = [f"tri={tri}"]
    if evenement_actif is not None:
        parts.append(f"evenement={evenement_actif.pk}")
    if type_filtre:
        parts.append(f"type={type_filtre}")
    return "&".join(parts)

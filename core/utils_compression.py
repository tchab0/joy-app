import subprocess
from pathlib import Path

from django.conf import settings


def compresser_media(media_item):
    """
    Compresse le fichier selon son type.
    Pour les photos, source = fichier_edite si présent, sinon original.

    Ne bascule pas un média déjà classé (publie / refuse) vers en_cours :
    sinon un reload juste après retouche le fait disparaître de son onglet.
    """
    src_path = media_item.source_compression()
    if not src_path or not src_path.exists():
        return

    src = str(src_path)
    dest_dir = Path(settings.MEDIA_ROOT) / "medias" / "compresses"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Stem : version éditée si présente (sidecar d'affichage distinct),
    # sinon source — pour ne pas écraser le compressé « original ».
    if media_item.fichier_edite:
        base_name = media_item.fichier_edite.name
    else:
        base_name = media_item.fichier.name if media_item.fichier else ""
    if not base_name:
        return
    nom_base = Path(base_name).stem

    prev_statut = media_item.statut
    prev_publie = bool(media_item.publie)
    # Progress UI only for items still in the submission pipeline
    track_progress = prev_statut not in ("publie", "refuse")
    if track_progress:
        media_item.statut = "en_cours"
        media_item.save(update_fields=["statut"])

    def _restore_statut(success):
        if prev_publie:
            return "publie"
        if prev_statut == "refuse":
            return "refuse"
        if success:
            return "en_attente"
        # failure: keep prior pipeline status if sensible
        if prev_statut in ("en_attente", "en_cours"):
            return "en_attente"
        return prev_statut or "en_attente"

    try:
        if media_item.type == "video":
            dest = dest_dir / f"{nom_base}.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-i", src,
                "-c:v", "libx265", "-crf", "28", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(dest)
            ], check=True, capture_output=True)

        elif media_item.type == "audio":
            dest = dest_dir / f"{nom_base}.m4a"
            subprocess.run([
                "ffmpeg", "-y", "-i", src,
                "-c:a", "aac", "-b:a", "128k",
                str(dest)
            ], check=True, capture_output=True)

        elif media_item.type == "photo":
            from io import BytesIO

            from django.core.files.base import ContentFile
            from PIL import Image

            dest = dest_dir / f"{nom_base}.webp"
            img = Image.open(src)
            img = img.convert("RGB")
            max_dim = 1280
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.LANCZOS)
            img.save(str(dest), "WEBP", quality=78, method=6)

            # Miniature grille (~400w) pour srcset mobile / cartes.
            thumb = img.copy()
            thumb_max = 400
            if max(thumb.size) > thumb_max:
                thumb.thumbnail((thumb_max, thumb_max), Image.LANCZOS)
            buf = BytesIO()
            thumb.save(buf, "WEBP", quality=72, method=6)
            thumb_name = f"{nom_base}-400.webp"
            if media_item.miniature:
                media_item.miniature.delete(save=False)
            media_item.miniature.save(
                thumb_name,
                ContentFile(buf.getvalue()),
                save=False,
            )
            media_item.save(update_fields=["miniature"])

        elif media_item.type == "pdf":
            try:
                import pikepdf
                dest = dest_dir / f"{nom_base}.pdf"
                with pikepdf.open(src) as pdf:
                    pdf.save(
                        str(dest),
                        compress_streams=True,
                        object_stream_mode=pikepdf.ObjectStreamMode.generate
                    )
            except ImportError:
                new_statut = _restore_statut(True)
                if media_item.statut != new_statut:
                    media_item.statut = new_statut
                    media_item.save(update_fields=["statut"])
                return
        else:
            return

        new_statut = _restore_statut(True)
        if media_item.statut != new_statut:
            media_item.statut = new_statut
            media_item.save(update_fields=["statut"])

    except Exception as e:
        new_statut = _restore_statut(False)
        media_item.statut = new_statut
        media_item.note_admin = f"Erreur compression : {e}"
        media_item.save(update_fields=["statut", "note_admin"])

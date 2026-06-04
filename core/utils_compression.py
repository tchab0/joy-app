import subprocess
import os
from pathlib import Path
from django.conf import settings


def compresser_media(media_item):
    """
    Compresse le fichier selon son type.
    Version compatible avec le schéma actuel sans fichier_compresse.
    """
    if not media_item.fichier:
        return

    src = media_item.fichier.path
    dest_dir = Path(settings.MEDIA_ROOT) / "medias" / "compresses"
    dest_dir.mkdir(parents=True, exist_ok=True)

    nom_base = Path(src).stem
    media_item.statut = "en_cours"
    media_item.save(update_fields=["statut"])

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
            from PIL import Image
            dest = dest_dir / f"{nom_base}.webp"
            img = Image.open(src)
            img = img.convert("RGB")
            max_dim = 1280
            if max(img.size) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.LANCZOS)
            img.save(str(dest), "WEBP", quality=78, method=6)

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
                media_item.statut = "publie" if media_item.publie else "en_attente"
                media_item.save(update_fields=["statut"])
                return
        else:
            return

        media_item.statut = "publie" if media_item.publie else "en_attente"
        media_item.save(update_fields=["statut"])

    except Exception as e:
        media_item.statut = "en_attente"
        media_item.note_admin = f"Erreur compression : {e}"
        media_item.save(update_fields=["statut", "note_admin"])

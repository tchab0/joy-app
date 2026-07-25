import subprocess
import os
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db.models import Case, CharField, Value, When


def compresser_media(media_item):
    """
    Compresse le fichier selon son type.
    Version compatible avec le schéma actuel sans fichier_compresse.
    """
    if not media_item.fichier:
        return

    src = media_item.fichier.path
    dest = media_item.chemin_compresse_destination()
    if not dest:
        return

    if Path(src).resolve() == dest.resolve():
        return

    dest_dir = Path(settings.MEDIA_ROOT) / "medias" / "compresses"
    dest_dir.mkdir(parents=True, exist_ok=True)
    temp_dest = dest.with_name(f".{dest.stem}.{uuid4().hex}{dest.suffix}")

    media_model = type(media_item)
    if not media_model.objects.filter(pk=media_item.pk).update(statut="en_cours"):
        return

    final_status = Case(
        When(publie=True, then=Value("publie")),
        default=Value("en_attente"),
        output_field=CharField(),
    )

    try:
        if media_item.type == "video":
            subprocess.run([
                "ffmpeg", "-y", "-i", src,
                "-c:v", "libx265", "-crf", "28", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(temp_dest)
            ], check=True, capture_output=True)

        elif media_item.type == "audio":
            subprocess.run([
                "ffmpeg", "-y", "-i", src,
                "-c:a", "aac", "-b:a", "128k",
                str(temp_dest)
            ], check=True, capture_output=True)

        elif media_item.type == "photo":
            from PIL import Image
            with Image.open(src) as source:
                img = source.convert("RGB")
                max_dim = 1280
                if max(img.size) > max_dim:
                    img.thumbnail((max_dim, max_dim), Image.LANCZOS)
                img.save(str(temp_dest), "WEBP", quality=78, method=6)

        elif media_item.type == "pdf":
            try:
                import pikepdf
                with pikepdf.open(src) as pdf:
                    pdf.save(
                        str(temp_dest),
                        compress_streams=True,
                        object_stream_mode=pikepdf.ObjectStreamMode.generate
                    )
            except ImportError:
                media_model.objects.filter(pk=media_item.pk).update(statut=final_status)
                return
        else:
            return

        os.replace(temp_dest, dest)
        if not media_model.objects.filter(pk=media_item.pk).update(
            statut=final_status,
            note_admin="",
        ):
            dest.unlink(missing_ok=True)

    except Exception as e:
        if temp_dest.exists():
            temp_dest.unlink()
        media_model.objects.filter(pk=media_item.pk).update(
            statut="en_attente",
            note_admin=f"Erreur compression : {e}",
        )

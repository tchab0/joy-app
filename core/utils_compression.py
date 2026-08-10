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
    model = type(media_item)
    claimed = model.objects.filter(
        pk=media_item.pk,
        statut="en_attente",
    ).update(statut="en_cours")
    if not claimed:
        return

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
                model.objects.filter(
                    pk=media_item.pk,
                    statut="en_cours",
                ).update(statut="en_attente")
                return
        else:
            return

        statut_final = (
            "publie"
            if model.objects.filter(pk=media_item.pk, publie=True).exists()
            else "en_attente"
        )
        model.objects.filter(
            pk=media_item.pk,
            statut="en_cours",
        ).update(statut=statut_final)

    except Exception as e:
        model.objects.filter(
            pk=media_item.pk,
            statut="en_cours",
        ).update(
            statut="en_attente",
            note_admin=f"Erreur compression : {e}",
        )

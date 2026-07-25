from pathlib import Path

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.models import MediaItem


def _delete_fieldfile_if_unused(model, instance, field_name):
    field_file = getattr(instance, field_name, None)
    if not field_file or not getattr(field_file, "name", ""):
        return

    other_refs = model._default_manager.filter(
        **{field_name: field_file.name}
    ).exclude(pk=instance.pk).exists()

    if other_refs:
        return

    storage = field_file.storage
    file_name = field_file.name

    def _delete():
        if storage.exists(file_name):
            field_file.delete(save=False)

    transaction.on_commit(_delete)


def _delete_compresse_sidecar(instance):
    compressé = instance.chemin_compresse()
    if not compressé or not compressé.exists():
        return

    path = compressé
    if instance.fichier and Path(instance.fichier.path).resolve() == path.resolve():
        # Le FileField est déjà basculé sur le compressé : le nettoyage
        # référencé ci-dessus est responsable de ce fichier partagé.
        return

    rel_path = path.relative_to(Path(instance._media_root())).as_posix()
    if MediaItem.objects.filter(fichier=rel_path).exclude(pk=instance.pk).exists():
        return

    def _delete():
        if path.exists():
            path.unlink()

    transaction.on_commit(_delete)


@receiver(post_delete, sender=MediaItem)
def media_files_cleanup(sender, instance, **kwargs):
    _delete_fieldfile_if_unused(sender, instance, "fichier")
    _delete_fieldfile_if_unused(sender, instance, "miniature")
    _delete_compresse_sidecar(instance)

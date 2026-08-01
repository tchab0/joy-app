"""
Télécharge le dossier Google Drive du répertoire vers MEDIA_ROOT/repertoire/_inbox/.

Prérequis (choisir l’un des deux) :
  pip install gdown
  # ou rclone + remote OAuth (ex. joydrive: pointant sur le dossier Drive)

Usage :
  # Authentifié (recommandé si des fichiers ne sont pas « Anyone with the link ») :
  PATH="$HOME/bin:$PATH" DJANGO_SETTINGS_MODULE=config.settings.prod \\
    python manage.py import_repertoire_inbox --method=rclone

  # Anonyme (gdown) — échoue si le partage n’est pas public :
  DJANGO_SETTINGS_MODULE=config.settings.prod \\
    python manage.py import_repertoire_inbox

Les deux méthodes sont reprises (rclone copy / gdown --continue) :
relancer la même commande après une interruption.

Les fichiers ne sont PAS publiés automatiquement : passer par l’atelier staff
(/repertoire/staff/) pour créer les morceaux et assigner les parties.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

DEFAULT_FOLDER_ID = "1IsWC_BYUFKk3fOM2llM-Tw3icsNQGOUM"
DRIVE_URL = "https://drive.google.com/drive/folders/{folder_id}"


class Command(BaseCommand):
    help = "Télécharge le répertoire Drive vers media/repertoire/_inbox/ (sans publier)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--folder-id",
            default=DEFAULT_FOLDER_ID,
            help="ID du dossier Google Drive",
        )
        parser.add_argument(
            "--method",
            choices=("gdown", "rclone"),
            default="gdown",
            help="Outil de téléchargement",
        )
        parser.add_argument(
            "--rclone-remote",
            default="joydrive:",
            help="Remote rclone (défaut: joydrive: — dossier racine déjà configuré)",
        )

    def handle(self, *args, **options):
        inbox = Path(settings.MEDIA_ROOT) / "repertoire" / "_inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        folder_id = options["folder_id"]
        method = options["method"]

        self.stdout.write(f"Inbox : {inbox}")
        self.stdout.write(f"Source : {DRIVE_URL.format(folder_id=folder_id)}")

        if method == "gdown":
            self._via_gdown(inbox, folder_id)
        else:
            remote = options["rclone_remote"]
            if not remote:
                raise CommandError("Indiquez --rclone-remote pour rclone.")
            self._via_rclone(inbox, remote)

        n_files = sum(1 for _ in inbox.rglob("*") if _.is_file())
        self.stdout.write(self.style.SUCCESS(
            f"Téléchargement terminé ({n_files} fichier(s) dans l’inbox)."
        ))
        self.stdout.write(
            "Ensuite : ouvrez /repertoire/staff/ pour créer les morceaux "
            "et découper / assigner les PDF."
        )

    def _via_gdown(self, inbox: Path, folder_id: str) -> None:
        try:
            import gdown  # noqa: F401
        except ImportError as exc:
            raise CommandError(
                "gdown n’est pas installé. Installez-le avec : pip install gdown"
            ) from exc

        url = DRIVE_URL.format(folder_id=folder_id)
        # gdown télécharge dans le cwd ; on cible l’inbox.
        dest = str(inbox)
        cmd = [
            sys.executable,
            "-m",
            "gdown",
            "--folder",
            url,
            "-O",
            dest,
            "--continue",
        ]
        self.stdout.write(" ".join(cmd))
        result = subprocess.run(cmd, check=False)
        n_files = sum(1 for _ in inbox.rglob("*") if _.is_file())
        if result.returncode != 0:
            msg = (
                f"gdown a quitté avec le code {result.returncode} "
                f"({n_files} fichier(s) déjà dans l’inbox). "
                "Causes fréquentes : un fichier du dossier n’est pas partagé "
                "en « Toute personne disposant du lien ». "
                "Corrigez le partage Drive, puis relancez la même commande "
                "(elle reprend grâce à --continue)."
            )
            if n_files == 0:
                raise CommandError(msg)
            self.stderr.write(self.style.WARNING(msg))
            return
        self.stdout.write(f"{n_files} fichier(s) dans l’inbox.")

    def _rclone_bin(self) -> str:
        for candidate in (
            shutil.which("rclone"),
            str(Path.home() / "bin" / "rclone"),
            "/home/deploy/bin/rclone",
        ):
            if candidate and Path(candidate).is_file():
                return candidate
        raise CommandError(
            "rclone introuvable. Installez-le dans ~/bin/rclone ou le PATH, "
            "puis configurez un remote (ex. joydrive:) via "
            "`rclone authorize \"drive\"`."
        )

    def _via_rclone(self, inbox: Path, remote: str) -> None:
        rclone = self._rclone_bin()
        # copy est déjà « resume » : saute les fichiers de même taille/mtime.
        cmd = [
            rclone,
            "copy",
            remote,
            str(inbox),
            "-P",
            "--transfers",
            "4",
            "--checkers",
            "8",
        ]
        self.stdout.write(" ".join(cmd))
        result = subprocess.run(cmd, check=False)
        n_files = sum(1 for _ in inbox.rglob("*") if _.is_file())
        if result.returncode != 0:
            raise CommandError(
                f"rclone a échoué (code {result.returncode}, "
                f"{n_files} fichier(s) déjà dans l’inbox). "
                "Vérifiez `rclone lsd joydrive:` puis relancez "
                "(la copie reprend où elle s’est arrêtée)."
            )
        self.stdout.write(f"{n_files} fichier(s) dans l’inbox.")

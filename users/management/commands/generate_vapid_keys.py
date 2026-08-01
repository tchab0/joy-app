from django.core.management.base import BaseCommand
from py_vapid import Vapid
from py_vapid.utils import b64urlencode
from cryptography.hazmat.primitives import serialization
from pathlib import Path


class Command(BaseCommand):
    help = (
        "Génère une paire de clés VAPID. "
        "Avec --write-env FICHIER, les ajoute au .env sans les afficher."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--write-env",
            type=str,
            default="",
            help="Chemin du .env où appendre les clés (sans affichage).",
        )

    def handle(self, *args, **options):
        v = Vapid()
        v.generate_keys()
        priv = v.private_pem()
        if isinstance(priv, bytes):
            priv = priv.decode()
        pub = v.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        pub_b64 = b64urlencode(pub)
        priv_env = priv.replace("\n", "\\n")
        block = (
            f"\n# Web Push VAPID\n"
            f"VAPID_PUBLIC_KEY={pub_b64}\n"
            f'VAPID_PRIVATE_KEY="{priv_env}"\n'
            f"VAPID_ADMIN_EMAIL=admin@jazz-orchestra-yonnais.fr\n"
        )
        write_env = (options.get("write_env") or "").strip()
        if write_env:
            path = Path(write_env)
            existing = path.read_text(encoding="utf-8") if path.is_file() else ""
            if "VAPID_PUBLIC_KEY=" in existing:
                self.stderr.write(
                    self.style.WARNING(
                        f"{path} contient déjà VAPID_PUBLIC_KEY — aucune écriture."
                    )
                )
                return
            with path.open("a", encoding="utf-8") as fh:
                fh.write(block)
            path.chmod(0o600)
            self.stdout.write(
                self.style.SUCCESS(f"Clés VAPID ajoutées à {path} (mode 600).")
            )
            return

        self.stdout.write("# Ajoutez ces lignes au fichier .env puis rechargez gunicorn :")
        self.stdout.write(f"VAPID_PUBLIC_KEY={pub_b64}")
        self.stdout.write(f'VAPID_PRIVATE_KEY="{priv_env}"')
        self.stdout.write("VAPID_ADMIN_EMAIL=admin@jazz-orchestra-yonnais.fr")

import os
import subprocess
from pathlib import Path

BASES = [
    "/var/www/jazz-orchestra-yonnais.fr",  # prod ? à ajuster
    "/var/www/jazz-orchestra-yonnais.dev", # dev ? à ajuster
]

def git_status(path):
    try:
        out = subprocess.check_output(
            ["git", "-C", path, "status", "--short", "--branch"],
            stderr=subprocess.STDOUT,
            text=True
        )
        return out
    except subprocess.CalledProcessError as e:
        return f"Erreur git: {e.output}"
    except FileNotFoundError:
        return "git non trouvé"

def main():
    for base in BASES:
        p = Path(base)
        print("="*80)
        print(f"Chemin : {p}")
        if not p.exists():
            print("-> n'existe pas")
            continue
        print("Contenu (niveau 1) :")
        for entry in sorted(p.iterdir()):
            print(f" - {entry.name}{'/' if entry.is_dir() else ''}")
        git_dir = p / ".git"
        if git_dir.exists():
            print("\nDépôt Git détecté, status :")
            print(git_status(str(p)))
        else:
            print("\nPas de dépôt Git dans ce répertoire.")
    print("="*80)

if __name__ == "__main__":
    main()

# Nextcloud — partitions MobileSheets (JOY)

Mini Nextcloud pour partager les PDF du répertoire au format stable
`<slug>/<poste>.pdf`, synchronisable depuis MobileSheets (Nextcloud natif).

## URL

https://cloud.jazz-orchestra-yonnais.fr

## Install

```bash
sudo bash /srv/jazz-orchestra-yonnais/repo/scripts/install_nextcloud.sh
sudo bash /srv/jazz-orchestra-yonnais/repo/deploy/nextcloud/finish_setup.sh
```

### DNS obligatoire

Enregistrement **A** chez le registrar (NS : `dns-parking.com`) :

| Type | Hôte | Valeur |
|------|------|--------|
| A | `cloud` | IP du VPS |

Sans ça, Let’s Encrypt → NXDOMAIN.

Puis exporter les PDF publiés :

```bash
cd /srv/jazz-orchestra-yonnais/repo
DJANGO_SETTINGS_MODULE=config.settings.prod \
  /srv/jazz-orchestra-yonnais/.venv/bin/python manage.py export_parts_for_nextcloud
```

## MobileSheets

1. Compte Nextcloud musicien (groupe `musiciens`).
2. Dossier partagé : **Partitions**.
3. MobileSheets → Sync Library → cloud → **Nextcloud** → dossier
   `MobileSheets-Lib` (vide au départ) **ou** import depuis `Partitions`.
4. Avant d’annoter un PDF partagé : **verrouiller** le fichier dans Nextcloud
   (menu ⋮ → Verrouiller). Les autres voient alors une alerte lecture seule.

## Verrous / lecture seule

Nextcloud app `files_lock` est activée. Un fichier verrouillé est en
lecture seule pour les autres (UI + clients qui respectent le verrou).

**Limite MobileSheets** : l’app travaille sur une **copie locale**. Elle ne
signale pas « fichier déjà ouvert » toute seule. Le verrou Nextcloud est le
signal d’équipe : verrouiller avant d’annoter, déverrouiller après sync.

L’export Django **n’écrase pas** un PDF plus récent côté cloud (préserve
les annotations embarquées).

## Layout disque

| Chemin | Rôle |
|--------|------|
| `data/nextcloud/.env` | Secrets (hors git) |
| `data/nextcloud/html` | Data Nextcloud |
| `data/nextcloud/db` | PostgreSQL |
| `data/nextcloud/scores/Partitions` | PDF exportés JOY |
| `data/nextcloud/scores/MobileSheets-Lib` | Dossier vide pour Sync Library MS |

## Ops

```bash
cd /srv/jazz-orchestra-yonnais/repo/deploy/nextcloud
docker compose --env-file /srv/jazz-orchestra-yonnais/data/nextcloud/.env logs -f app
docker compose --env-file /srv/jazz-orchestra-yonnais/data/nextcloud/.env exec -u www-data app php occ status
```

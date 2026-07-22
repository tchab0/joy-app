#!/usr/bin/env bash
# Installe Docker (si besoin) + Nextcloud minimal + nginx cloud.* + verrous.
# Usage : sudo bash deploy/nextcloud/install.sh
set -euo pipefail

REPO=/srv/jazz-orchestra-yonnais/repo
DATA=/srv/jazz-orchestra-yonnais/data/nextcloud
COMPOSE_DIR="$REPO/deploy/nextcloud"
DOMAIN=cloud.jazz-orchestra-yonnais.fr
SITE_SRC="$REPO/deploy/nginx/cloud.jazz-orchestra-yonnais.fr"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Relancer avec sudo : sudo bash $0" >&2
  exit 1
fi

mkdir -p "$DATA"/{html,db,scores/Partitions,scores/MobileSheets-Lib}
chmod 750 "$DATA"
chown -R deploy:deploy "$DATA/scores"

# --- Secrets ---
ENV_FILE="$DATA/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  umask 077
  PG_PASS="$(openssl rand -base64 24 | tr -d '=+/' | cut -c1-32)"
  ADMIN_PASS="$(openssl rand -base64 18 | tr -d '=+/' | cut -c1-24)"
  cat >"$ENV_FILE" <<EOF
POSTGRES_PASSWORD=${PG_PASS}
NEXTCLOUD_ADMIN_USER=admin
NEXTCLOUD_ADMIN_PASSWORD=${ADMIN_PASS}
NEXTCLOUD_TRUSTED_DOMAINS=${DOMAIN}
OVERWRITEHOST=${DOMAIN}
OVERWRITECLIURL=https://${DOMAIN}
EOF
  chown deploy:deploy "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Secrets écrits dans $ENV_FILE"
  echo "Mot de passe admin Nextcloud : ${ADMIN_PASS}"
  echo "(conservez-le ; il ne sera plus réaffiché par ce script)"
else
  echo "Réutilisation de $ENV_FILE"
fi

# --- Docker ---
if ! command -v docker >/dev/null 2>&1; then
  echo "Installation de Docker…"
  apt-get update -y
  apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
  fi
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    >/etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
  usermod -aG docker deploy || true
fi

# --- Compose ---
cd "$COMPOSE_DIR"
docker compose --env-file "$ENV_FILE" pull
docker compose --env-file "$ENV_FILE" up -d

echo "Attente Nextcloud (status.php)…"
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:8088/status.php" >/dev/null 2>&1; then
    echo "Nextcloud répond (tentative $i)."
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    echo "Timeout : Nextcloud ne répond pas sur :8088" >&2
    docker compose --env-file "$ENV_FILE" logs --tail=80 app >&2 || true
    exit 1
  fi
  sleep 5
done

occ() {
  docker compose --env-file "$ENV_FILE" exec -T -u www-data app php occ "$@"
}

# Attendre fin install automatique
for i in $(seq 1 60); do
  if occ status 2>/dev/null | grep -q "installed: true"; then
    break
  fi
  sleep 5
done

occ status || true

# Apps utiles (verrou utilisateur = alerte lecture seule)
occ app:enable files_sharing || true
occ app:enable files_external || true
if ! occ app:enable files_lock 2>/dev/null; then
  occ app:install files_lock 2>/dev/null || true
  occ app:enable files_lock 2>/dev/null || true
fi
occ app:disable firstrunwizard 2>/dev/null || true

# Verrous fichiers (UI + WebDAV) — les autres voient lecture seule
occ config:app:set files_lock lock_timeout --value=0 2>/dev/null || true
occ config:system:set filelocking.enabled --value=true --type=boolean || true

# Config proxy HTTPS
occ config:system:set trusted_domains 0 --value=localhost || true
occ config:system:set trusted_domains 1 --value="$DOMAIN"
occ config:system:set overwrite.cli.url --value="https://${DOMAIN}"
occ config:system:set overwriteprotocol --value=https
occ config:system:set overwritehost --value="$DOMAIN"
occ config:system:set allow_local_remote_servers --value=true --type=boolean

# Stockage externe : dossier scores monté
# Mount point dans le conteneur : /mnt/joy-scores
# Exposé via Local external storage + groupe musiciens.

# Groupe musiciens
occ group:add musiciens 2>/dev/null || true

# Créer dossiers dans le data admin si besoin (via stockage local lié)
SCORES_HOST="$DATA/scores"
PARTITIONS="$SCORES_HOST/Partitions"
MSLIB="$SCORES_HOST/MobileSheets-Lib"
mkdir -p "$PARTITIONS" "$MSLIB"

cat >"$PARTITIONS/README-MobileSheets.txt" <<'EOF'
Partitions Jazz Orchestra Yonnais
=================================

Structure : <slug-morceau>/<poste>.pdf
Exemple   : night-in-tunisia/alto_1.pdf

MobileSheets
------------
Option A — Sync Library (annotations MS partagées)
  1. Ouvrir le dossier cloud "MobileSheets-Lib" (vide au départ).
  2. Sur une tablette « maître » : Sync Library → Nextcloud → ce dossier
     → Upload / Update Folder.
  3. Sur les autres : Sync Library → même dossier → Update Device.
  4. Avant d'annoter : verrouiller le PDF concerné dans Nextcloud
     (menu ⋮ → Verrouiller) pour signaler lecture seule aux autres.

Option B — Import depuis Partitions/
  Importer les PDF depuis ce dossier, puis activer le sync library
  si vous voulez partager les annotations MobileSheets.

Verrou / lecture seule
----------------------
Nextcloud ne détecte pas l'ouverture dans MobileSheets (copie locale).
Le verrou Nextcloud est le signal d'équipe obligatoire avant annotation.
EOF

chown -R www-data:www-data "$DATA/html" 2>/dev/null || true
# Le bind-mount scores doit être accessible www-data (uid 33 dans le conteneur)
chown -R 33:33 "$SCORES_HOST" || chown -R www-data:www-data "$SCORES_HOST" || true
chmod -R u+rwX,g+rwX "$SCORES_HOST"

# External storage : Local → /mnt/joy-scores
mount_id_for() {
  local name="$1"
  occ files_external:list 2>/dev/null | awk -v n="$name" '
    index($0, n) {
      for (i = 1; i <= NF; i++) {
        if ($i ~ /^[0-9]+$/) { print $i; exit }
      }
    }'
}

EXISTING_ID="$(mount_id_for Partitions-JOY || true)"
if [[ -n "${EXISTING_ID:-}" ]]; then
  echo "Montage Partitions-JOY déjà présent (id=${EXISTING_ID})"
else
  occ files_external:create Partitions-JOY local null::null \
    -c datadir=/mnt/joy-scores || true
  EXISTING_ID="$(mount_id_for Partitions-JOY || true)"
fi

if [[ -n "${EXISTING_ID:-}" ]]; then
  occ files_external:option "$EXISTING_ID" enable_sharing true || true
  occ files_external:applicable --add-group musiciens "$EXISTING_ID" || true
  occ files_external:applicable --add-user admin "$EXISTING_ID" || true
else
  echo "ATTENTION : montage Partitions-JOY introuvable" >&2
  occ files_external:list || true
fi

# Scan fichiers
occ files:scan --path=/admin 2>/dev/null || occ files:scan --all || true

# --- TLS + nginx ---
if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
  if command -v certbot >/dev/null 2>&1; then
    # Cert temporaire nginx HTTP-only pour challenge, ou certbot nginx
    apt-get install -y certbot python3-certbot-nginx || true
    # Placeholders SSL : utiliser le cert apex le temps du premier certbot
    if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
      # Vhost bootstrap HTTP pour ACME
      cat >/etc/nginx/sites-available/${DOMAIN}.bootstrap <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 200 'joy-nextcloud-bootstrap'; add_header Content-Type text/plain; }
}
EOF
      ln -sfn /etc/nginx/sites-available/${DOMAIN}.bootstrap /etc/nginx/sites-enabled/${DOMAIN}.bootstrap
      nginx -t && systemctl reload nginx
      certbot certonly --webroot -w /var/www/html -d "$DOMAIN" --non-interactive --agree-tos \
        --register-unsafely-without-email \
        || certbot certonly --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        --register-unsafely-without-email \
        || true
      rm -f /etc/nginx/sites-enabled/${DOMAIN}.bootstrap
    fi
  fi
fi

if [[ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
  install -m 644 "$SITE_SRC" /etc/nginx/sites-available/${DOMAIN}
  ln -sfn /etc/nginx/sites-available/${DOMAIN} /etc/nginx/sites-enabled/${DOMAIN}
  nginx -t
  systemctl reload nginx
  echo "nginx : https://${DOMAIN} OK"
else
  echo "ATTENTION : certificat TLS manquant pour ${DOMAIN}." >&2
  echo "Créez le DNS A ${DOMAIN} → IP serveur, puis :" >&2
  echo "  sudo certbot certonly --nginx -d ${DOMAIN}" >&2
  echo "  sudo install -m 644 $SITE_SRC /etc/nginx/sites-available/${DOMAIN}" >&2
  echo "  sudo ln -sfn /etc/nginx/sites-available/${DOMAIN} /etc/nginx/sites-enabled/${DOMAIN}" >&2
  echo "  sudo nginx -t && sudo systemctl reload nginx" >&2
fi

# Timer export PDF
install -m 644 "$REPO/deploy/systemd/joy-nextcloud-export.service" /etc/systemd/system/
install -m 644 "$REPO/deploy/systemd/joy-nextcloud-export.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now joy-nextcloud-export.timer

echo
echo "=== Nextcloud installé ==="
echo "URL     : https://${DOMAIN}"
echo "Admin   : $(grep NEXTCLOUD_ADMIN_USER "$ENV_FILE" | cut -d= -f2)"
echo "Secrets : $ENV_FILE"
echo "Scores  : $PARTITIONS"
echo
echo "Ensuite :"
echo "  1. Créer des comptes musiciens (groupe musiciens)"
echo "  2. Partager Partitions-JOY / Partitions en lecture-écriture"
echo "  3. Export : cd $REPO && DJANGO_SETTINGS_MODULE=config.settings.prod \\"
echo "       /srv/jazz-orchestra-yonnais/.venv/bin/python manage.py export_parts_for_nextcloud"
echo "  4. Sur MobileSheets : Nextcloud → dossier Partitions ou MobileSheets-Lib"

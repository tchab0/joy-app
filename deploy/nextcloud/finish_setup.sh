#!/usr/bin/env bash
# Finalise partage Partitions-JOY + verrous, puis HTTPS si le DNS cloud. existe.
# Usage : sudo bash deploy/nextcloud/finish_setup.sh
set -euo pipefail

COMPOSE_DIR=/srv/jazz-orchestra-yonnais/repo/deploy/nextcloud
ENV_FILE=/srv/jazz-orchestra-yonnais/data/nextcloud/.env
DOMAIN=cloud.jazz-orchestra-yonnais.fr
SITE_SRC=/srv/jazz-orchestra-yonnais/repo/deploy/nginx/cloud.jazz-orchestra-yonnais.fr
SERVER_IP="$(hostname -I | awk '{print $1}')"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Relancer avec sudo : sudo bash $0" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Manque $ENV_FILE" >&2
  exit 1
fi

cd "$COMPOSE_DIR"
occ() {
  docker compose --env-file "$ENV_FILE" exec -T -u www-data app php occ "$@"
}

mount_id_for() {
  local name="$1"
  occ files_external:list 2>/dev/null | awk -v n="$name" '
    index($0, n) {
      for (i = 1; i <= NF; i++) {
        if ($i ~ /^[0-9]+$/) { print $i; exit }
      }
    }'
}

echo "=== Verrous + stockage externe ==="
occ app:enable files_sharing || true
occ app:enable files_external || true
if ! occ app:enable files_lock 2>/dev/null; then
  occ app:install files_lock || true
  occ app:enable files_lock || true
fi
occ config:system:set filelocking.enabled --value=true --type=boolean
occ group:add musiciens 2>/dev/null || true

MOUNT_ID="$(mount_id_for Partitions-JOY || true)"
if [[ -z "${MOUNT_ID:-}" ]]; then
  occ files_external:create Partitions-JOY local null::null \
    -c datadir=/mnt/joy-scores
  MOUNT_ID="$(mount_id_for Partitions-JOY || true)"
fi

if [[ -z "${MOUNT_ID:-}" ]]; then
  echo "Impossible de trouver l'id du montage Partitions-JOY" >&2
  occ files_external:list || true
  exit 1
fi

echo "Mount Partitions-JOY id=${MOUNT_ID}"
occ files_external:option "$MOUNT_ID" enable_sharing true
occ files_external:applicable --add-user admin "$MOUNT_ID" || true
occ files_external:applicable --add-group musiciens "$MOUNT_ID" || true
# Visible pour tous les utilisateurs authentifiés (orchestre)
occ files_external:applicable --add-group admin "$MOUNT_ID" 2>/dev/null || true

occ files:scan --all || true
occ files_external:list

echo
echo "=== DNS ${DOMAIN} ==="
PUBLIC_A="$(dig @8.8.8.8 +short "$DOMAIN" A | tail -n1 || true)"
if [[ -z "$PUBLIC_A" ]]; then
  cat <<EOF
DNS public : PAS d'enregistrement A pour ${DOMAIN}.

Chez votre registrar / DNS (ns1.dns-parking.com) créez :
  Type A | Hôte cloud | Valeur ${SERVER_IP}

Puis relancez :
  sudo bash $0

En attendant, Nextcloud répond en local :
  curl -s http://127.0.0.1:8088/status.php
EOF
  exit 0
fi

echo "DNS public OK : ${DOMAIN} → ${PUBLIC_A}"

# Vhost HTTP bootstrap si pas encore de cert
if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
  cat >/etc/nginx/sites-available/${DOMAIN}.bootstrap <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        client_max_body_size 512M;
    }
}
EOF
  ln -sfn /etc/nginx/sites-available/${DOMAIN}.bootstrap /etc/nginx/sites-enabled/${DOMAIN}.bootstrap
  rm -f /etc/nginx/sites-enabled/${DOMAIN} 2>/dev/null || true
  nginx -t && systemctl reload nginx
  certbot certonly --webroot -w /var/www/html -d "$DOMAIN" --non-interactive --agree-tos \
    --register-unsafely-without-email \
    || certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
    --register-unsafely-without-email
fi

if [[ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
  install -m 644 "$SITE_SRC" /etc/nginx/sites-available/${DOMAIN}
  ln -sfn /etc/nginx/sites-available/${DOMAIN} /etc/nginx/sites-enabled/${DOMAIN}
  rm -f /etc/nginx/sites-enabled/${DOMAIN}.bootstrap
  nginx -t && systemctl reload nginx
  echo "HTTPS OK : https://${DOMAIN}"
else
  echo "Certificat toujours manquant pour ${DOMAIN}" >&2
  exit 1
fi

echo
echo "Admin : voir ${ENV_FILE} (NEXTCLOUD_ADMIN_PASSWORD)"
echo "Connectez-vous, créez des comptes dans le groupe « musiciens »."
echo "Dossier cloud : Partitions-JOY / Partitions / MobileSheets-Lib"

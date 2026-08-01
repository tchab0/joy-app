#!/usr/bin/env bash
# Installe Daphne (WebSockets), proxy nginx /ws/, timer digest notifications.
# À lancer avec sudo : sudo bash scripts/install_chat_infra.sh
set -euo pipefail

REPO=/srv/jazz-orchestra-yonnais/repo
SYSTEMD_SRC="$REPO/deploy/systemd"
NGINX_SRC="$REPO/deploy/nginx"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Relancer avec sudo : sudo bash $0" >&2
  exit 1
fi

install -m 644 "$SYSTEMD_SRC/daphne-jazz-orchestra-yonnais.service" /etc/systemd/system/
install -m 644 "$SYSTEMD_SRC/daphne-jazz-orchestra-yonnais-dev.service" /etc/systemd/system/
install -m 644 "$SYSTEMD_SRC/joy-chat-digest.service" /etc/systemd/system/
install -m 644 "$SYSTEMD_SRC/joy-chat-digest.timer" /etc/systemd/system/

install -m 644 "$NGINX_SRC/ws-map.conf" /etc/nginx/conf.d/joy-ws-map.conf
install -m 644 "$NGINX_SRC/jazz-orchestra-yonnais.fr" /etc/nginx/sites-available/jazz-orchestra-yonnais.fr

nginx -t
systemctl daemon-reload
systemctl enable --now daphne-jazz-orchestra-yonnais.service
systemctl enable --now daphne-jazz-orchestra-yonnais-dev.service
systemctl enable --now joy-chat-digest.timer
systemctl reload nginx

echo "OK — Daphne prod/dev, nginx /ws/, timer digest."
systemctl --no-pager --full status daphne-jazz-orchestra-yonnais.service | head -15
systemctl --no-pager list-timers joy-chat-digest.timer | head -5

#!/usr/bin/env bash
# Installe le timer systemd de purge des mails spam SEO (anglais).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEMD_SRC="$ROOT/deploy/systemd"

if [[ $EUID -ne 0 ]]; then
  echo "Relancer avec sudo : sudo bash $0" >&2
  exit 1
fi

install -m 644 "$SYSTEMD_SRC/joy-purge-seo-spam-mail.service" /etc/systemd/system/
install -m 644 "$SYSTEMD_SRC/joy-purge-seo-spam-mail.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now joy-purge-seo-spam-mail.timer

echo "OK — timer joy-purge-seo-spam-mail (toutes les 30 min)."
echo "Assure-toi que .env contient EMAIL_HOST_PASSWORD (ou IMAP_PASSWORD)."
systemctl --no-pager list-timers joy-purge-seo-spam-mail.timer | head -5

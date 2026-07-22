#!/usr/bin/env bash
# Installe le timer quotidien de demande de photos J+7.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEMD_SRC="$ROOT/deploy/systemd"

install -m 644 "$SYSTEMD_SRC/joy-event-photos.service" /etc/systemd/system/
install -m 644 "$SYSTEMD_SRC/joy-event-photos.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now joy-event-photos.timer

echo "OK — timer joy-event-photos (tous les jours à 10h)."
systemctl --no-pager list-timers joy-event-photos.timer | head -5

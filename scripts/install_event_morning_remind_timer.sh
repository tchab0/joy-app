#!/usr/bin/env bash
# Installe le timer quotidien de rappel matinal (jour J, 7h).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEMD_SRC="$ROOT/deploy/systemd"

install -m 644 "$SYSTEMD_SRC/joy-event-morning-remind.service" /etc/systemd/system/
install -m 644 "$SYSTEMD_SRC/joy-event-morning-remind.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now joy-event-morning-remind.timer

echo "OK — timer joy-event-morning-remind (tous les jours à 7h)."
systemctl --no-pager list-timers joy-event-morning-remind.timer | head -5

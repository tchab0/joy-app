#!/usr/bin/env bash
# Installe le timer quotidien de rappel deadline sondage (J−7).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEMD_SRC="$ROOT/deploy/systemd"

install -m 644 "$SYSTEMD_SRC/joy-poll-deadline-remind.service" /etc/systemd/system/
install -m 644 "$SYSTEMD_SRC/joy-poll-deadline-remind.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now joy-poll-deadline-remind.timer

echo "OK — timer joy-poll-deadline-remind (tous les jours à 10h30)."
systemctl --no-pager list-timers joy-poll-deadline-remind.timer | head -5

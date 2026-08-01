#!/usr/bin/env bash
# Installe le timer quotidien de relance « peut-être ».
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEMD_SRC="$ROOT/deploy/systemd"

install -m 644 "$SYSTEMD_SRC/joy-maybe-remind.service" /etc/systemd/system/
install -m 644 "$SYSTEMD_SRC/joy-maybe-remind.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now joy-maybe-remind.timer

echo "OK — timer joy-maybe-remind (tous les jours à 10h15)."
systemctl --no-pager list-timers joy-maybe-remind.timer | head -5

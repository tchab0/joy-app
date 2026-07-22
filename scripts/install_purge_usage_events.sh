#!/usr/bin/env bash
# Installe le timer systemd de purge des UsageEvent (stats).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEMD_SRC="$ROOT/deploy/systemd"

install -m 644 "$SYSTEMD_SRC/joy-purge-usage-events.service" /etc/systemd/system/
install -m 644 "$SYSTEMD_SRC/joy-purge-usage-events.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now joy-purge-usage-events.timer

echo "OK — timer joy-purge-usage-events (lundi 04:15)."
systemctl --no-pager list-timers joy-purge-usage-events.timer | head -5

#!/usr/bin/env bash
# Reconfigure occ (verrous, stockage externe) si Nextcloud tourne déjà.
# Usage : sudo bash deploy/nextcloud/configure_locks_and_share.sh
set -euo pipefail

exec bash /srv/jazz-orchestra-yonnais/repo/deploy/nextcloud/finish_setup.sh "$@"

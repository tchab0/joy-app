#!/usr/bin/env bash
# Installe Nextcloud (partitions MobileSheets) — wrapper.
# Usage : sudo bash scripts/install_nextcloud.sh
set -euo pipefail
exec bash /srv/jazz-orchestra-yonnais/repo/deploy/nextcloud/install.sh "$@"

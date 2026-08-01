#!/usr/bin/env bash
# Applique gzip_types + HTTP/2 sur la config nginx live (nécessite sudo).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

sudo cp "$ROOT/deploy/nginx/http-perf.conf" /etc/nginx/conf.d/http-perf.conf

# Sync miroir repo → sites-available (source of truth ; syntaxe http2 on;)
sudo cp "$ROOT/deploy/nginx/jazz-orchestra-yonnais.fr" \
  /etc/nginx/sites-available/jazz-orchestra-yonnais.fr
if [[ -f "$ROOT/deploy/nginx/cloud.jazz-orchestra-yonnais.fr" ]]; then
  sudo cp "$ROOT/deploy/nginx/cloud.jazz-orchestra-yonnais.fr" \
    /etc/nginx/sites-available/cloud.jazz-orchestra-yonnais.fr
fi

sudo nginx -t
sudo systemctl reload nginx

echo "OK — smoke gzip/http2:"
curl -sI -H 'Accept-Encoding: gzip' \
  'https://jazz-orchestra-yonnais.fr/static/core/event-map.js' \
  | tr -d '\r' | grep -iE 'HTTP/|content-encoding|content-type' || true
curl -sI --http2 'https://jazz-orchestra-yonnais.fr/' \
  | tr -d '\r' | head -1 || true

#!/usr/bin/env bash
# Run Heracles (image $IMAGE, default heracles-ds) against the 389 DS test directory of setup.sh.
#   deploy/ds/heracles.sh <ds-port> <app-port> [container-name]
set -euo pipefail
DS_PORT=${1:-3389}
APP_PORT=${2:-8420}
NAME=${3:-heracles-ds-app}
IMAGE=${IMAGE:-heracles-ds}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
CONF=$(mktemp -d)/heracles.yaml
sed -e "s#uri: ldap://ldap:1389#uri: ldap://127.0.0.1:${DS_PORT}#" \
    -e "s#bind_dn: cn=admin,dc=heracles,dc=test#bind_dn: cn=Directory Manager#" \
    "$ROOT/deploy/e2e/heracles.yaml" > "$CONF"
chmod 644 "$CONF"
docker run -d --name "$NAME" --network host -v "$CONF:/etc/heracles/heracles.yaml:ro" "$IMAGE" \
  heracles serve --host 127.0.0.1 --port "$APP_PORT" --with-worker >/dev/null
for _ in $(seq 1 60); do
  curl -sf "http://127.0.0.1:${APP_PORT}/readyz" >/dev/null && { echo "Heracles on http://127.0.0.1:${APP_PORT}"; exit 0; }
  sleep 2
done
docker logs "$NAME" | tail -40
exit 1

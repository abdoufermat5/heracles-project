#!/usr/bin/env bash
# A 389 Directory Server test directory with the Heracles schema and the dev seed.
#
#   deploy/ds/setup.sh [container-name] [host-port]      (defaults: heracles-ds, 3389)
#
# Starts the container, creates the dc=heracles,dc=test backend, loads the schema files of
# deploy/ldap/schema online (definitions the server already ships are skipped) and adds
# deploy/ldap/seed.ldif. The Directory Manager password is "admin" (test only).
set -euo pipefail
NAME=${1:-heracles-ds}
PORT=${2:-3389}
IMAGE=${HERACLES_DS_IMAGE:-docker.io/389ds/dirsrv:latest}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SUFFIX=dc=heracles,dc=test
DM=(-x -H ldap://localhost:3389 -D "cn=Directory Manager" -w admin)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

docker run -d --name "$NAME" -p "127.0.0.1:${PORT}:3389" -e DS_DM_PASSWORD=admin "$IMAGE" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$NAME" ldapsearch "${DM[@]}" -b "" -s base >/dev/null 2>&1 && break
  sleep 3
done
docker exec "$NAME" dsconf localhost backend create --suffix "$SUFFIX" --be-name userroot >/dev/null

# names the server already defines
docker exec "$NAME" ldapsearch "${DM[@]}" -o ldif-wrap=no -b cn=schema -s base attributeTypes objectClasses \
  | python3 -c "
import re, sys
for line in sys.stdin:
    m = re.search(r\"NAME\s+(?:'([^']+)'|\(([^)]*)\))\", line)
    if m:
        print(m.group(1) or ' '.join(re.findall(r\"'([^']+)'\", m.group(2))))
" > "$WORK/existing.txt"

# Heracles schema first, then the third-party schemas present (some are local only)
mapfile -t FILES < <(ls "$ROOT"/deploy/ldap/schema/heracles.ldif; ls "$ROOT"/deploy/ldap/schema/[0-9]*.ldif 2>/dev/null)
python3 "$ROOT/deploy/ldap/ldif2ds.py" "${FILES[@]}" --skip "$WORK/existing.txt" > "$WORK/schema.ldif"
docker cp "$WORK/schema.ldif" "$NAME:/tmp/schema.ldif"
docker exec "$NAME" ldapmodify "${DM[@]}" -f /tmp/schema.ldif >/dev/null

docker cp "$ROOT/deploy/ldap/seed.ldif" "$NAME:/tmp/seed.ldif"
docker exec "$NAME" ldapadd "${DM[@]}" -f /tmp/seed.ldif >/dev/null
echo "389 Directory Server ready on ldap://127.0.0.1:${PORT} (cn=Directory Manager / admin)"

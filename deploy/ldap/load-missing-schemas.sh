#!/usr/bin/env bash
# Load into the running test directory every schema of deploy/ldap/schema it does not have yet.
#
# The test server only loads the schema files at the first start of its data volume, so a
# schema added later (a new plugin, a newly fetched third-party schema) would otherwise need
# the volume, and the data in it, to be dropped. Schemas already loaded are left as they are.
#
#   deploy/ldap/load-missing-schemas.sh docker compose -f deploy/docker-compose.yml
set -euo pipefail
DIR=$(cd "$(dirname "$0")" && pwd)
if [ "$#" -eq 0 ]; then
  set -- docker compose -f "$DIR/../docker-compose.yml"
fi

loaded=$("$@" exec -T ldap ldapsearch -Y EXTERNAL -H ldapi:/// -LLL -Q \
  -b cn=schema,cn=config -s one cn | sed -n 's/^cn: {[0-9]*}//p')

for file in "$DIR"/schema/*.ldif; do
  name=$(sed -n 's/^cn: //p' "$file" | head -n 1)
  [ -n "$name" ] || continue
  if printf '%s\n' "$loaded" | grep -qxF "$name"; then
    continue
  fi
  echo "ldap: loading the ${name} schema ($(basename "$file"))"
  "$@" exec -T ldap ldapadd -Y EXTERNAL -H ldapi:/// -Q <"$file" >/dev/null
done

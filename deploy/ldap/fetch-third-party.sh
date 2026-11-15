#!/usr/bin/env bash
# Fetch the third-party schemas the test stacks need (not distributed with Heracles), at pinned
# upstream commits checked by SHA-256, and convert them to cn=config LDIF in deploy/ldap/schema.
# Files already present are kept. Used by CI; locally, any copy of the same schemas works too.
set -euo pipefail
DIR=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

fetch() { # <target ldif> <name> <url> <sha256>
  if [ -e "$DIR/schema/$1" ]; then return; fi
  curl -sSfL "$3" -o "$WORK/$2.schema"
  echo "$4  $WORK/$2.schema" | sha256sum -c --quiet -
  python3 "$DIR/schema2ldif.py" "$WORK/$2.schema" -o "$WORK/out" --prefix "${1%%-*}-"
  mv "$WORK/out/$1" "$DIR/schema/$1"
  echo "fetched $1"
}

fetch 04-sudo.ldif sudo \
  https://raw.githubusercontent.com/sudo-project/sudo/40e1489abbc4b0333883428a78a3147504dd28eb/docs/schema.OpenLDAP \
  c3b81a7fb19f1309fe830ec7760cbd99f7de2ac0276496f51cddb4b1a14173d4
fetch 05-openssh-lpk.ldif openssh-lpk \
  https://raw.githubusercontent.com/AndriiGrytsenko/openssh-ldap-publickey/afc095a0e9be1ca0a1c47ac2891f70cda2cdbfe2/misc/openssh-lpk-openldap.schema \
  d456a6d55cfea5168f2be6ddd7e761ed2304062b4e89cfbd17bad38f5ac0a21e

#!/bin/bash
# Start the dev FTP server against the dev directory.
set -euo pipefail

LDAP_URI="${LDAP_URI:-ldap://ldap:1389}"
BASE_DN="${BASE_DN:-dc=heracles,dc=test}"
LDAP_ADMIN_DN="${LDAP_ADMIN_DN:-cn=admin,${BASE_DN}}"
LDAP_ADMIN_PASSWORD="${LDAP_ADMIN_PASSWORD:-admin}"

echo "ftp: waiting for the directory at ${LDAP_URI}"
for _ in $(seq 1 60); do
	if ldapsearch -x -H "$LDAP_URI" -D "$LDAP_ADMIN_DN" -w "$LDAP_ADMIN_PASSWORD" \
		-s base -b "$BASE_DN" dn >/dev/null 2>&1; then
		break
	fi
	sleep 1
done

echo "ftp: starting pure-ftpd (accounts from the directory)"
exec /usr/sbin/pure-ftpd-ldap \
	--login ldap:/etc/pure-ftpd/db/heracles-ldap.conf \
	--chrooteveryone \
	--createhomedir \
	--noanonymous \
	--ipv4only \
	--bind 0.0.0.0,21 \
	--passiveportrange 30000:30009 \
	--forcepassiveip 127.0.0.1 \
	--maxclientsnumber 20 \
	--maxclientsperip 10 \
	--altlog clf:/var/log/pure-ftpd.log

#!/bin/bash
# Start the dev DHCP server from the configuration stored in the dev directory.
set -euo pipefail

LDAP_URI="${LDAP_URI:-ldap://ldap:1389}"
BASE_DN="${BASE_DN:-dc=heracles,dc=test}"
LDAP_ADMIN_DN="${LDAP_ADMIN_DN:-cn=admin,${BASE_DN}}"
LDAP_ADMIN_PASSWORD="${LDAP_ADMIN_PASSWORD:-admin}"
DHCP_SERVICE_DN="${DHCP_SERVICE_DN:-cn=dev-dhcp,ou=dhcp,${BASE_DN}}"
export LDAP_URI BASE_DN LDAP_ADMIN_DN LDAP_ADMIN_PASSWORD DHCP_SERVICE_DN

echo "dhcp: waiting for the directory at ${LDAP_URI}"
for _ in $(seq 1 60); do
	if ldapsearch -x -H "$LDAP_URI" -D "$LDAP_ADMIN_DN" -w "$LDAP_ADMIN_PASSWORD" \
		-s base -b "$BASE_DN" dn >/dev/null 2>&1; then
		break
	fi
	sleep 1
done

mkdir -p /run/heracles-dhcp /var/lib/dhcp
touch /var/lib/dhcp/dhcpd.leases

echo "dhcp: rendering the configuration from ${DHCP_SERVICE_DN}"
render-dhcpd-conf /etc/dhcp/dhcpd.conf /run/heracles-dhcp/subnets.json
cat /etc/dhcp/dhcpd.conf

interface="$(render-dhcpd-conf --interface /run/heracles-dhcp/subnets.json)"
echo "dhcp: serving the isolated network on ${interface}"
exec dhcpd -4 -d \
	-cf /etc/dhcp/dhcpd.conf \
	-lf /var/lib/dhcp/dhcpd.leases \
	-pf /run/heracles-dhcp/dhcpd.pid \
	"$interface"

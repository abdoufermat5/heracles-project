#!/bin/bash
# Start the dev Kerberos KDC against the dev directory.
#
# First run (no realm in the directory yet):
#   * creates the realm container below the base DN, with the people subtree as the
#     place principals may be linked to;
#   * creates one principal per seeded user, linked to its existing entry and with the
#     same password as its directory account, plus an admin principal and a service
#     principal for the dev API.
# Later runs keep everything the directory holds; the master key stash and the directory
# bind password live in the volume, and are rebuilt from the dev secrets when it is new.
set -euo pipefail

LDAP_URI="${LDAP_URI:-ldap://ldap:1389}"
BASE_DN="${BASE_DN:-dc=heracles,dc=test}"
LDAP_ADMIN_DN="${LDAP_ADMIN_DN:-cn=admin,${BASE_DN}}"
LDAP_ADMIN_PASSWORD="${LDAP_ADMIN_PASSWORD:-admin}"
REALM="${KRB_REALM:-HERACLES.TEST}"
MASTER_PASSWORD="${KRB_MASTER_PASSWORD:-master-secret}"
# "<principal>:<password>:<entry rdn below the people subtree>" (empty rdn: not linked)
USERS="${KRB_USERS:-alice:alice-secret:uid=alice bob:bob-secret:uid=bob carol:carol-secret:uid=carol}"
ADMIN_PASSWORD="${KRB_ADMIN_PASSWORD:-admin}"
SERVICES="${KRB_SERVICES:-HTTP/heracles.heracles.test host/kdc.heracles.test}"

PEOPLE_DN="ou=people,${BASE_DN}"
CONTAINER_DN="cn=krbContainer,${BASE_DN}"
STATE=/var/lib/krb5kdc
KEYFILE="${STATE}/service.keyfile"
STASH="${STATE}/stash"

mkdir -p /etc/krb5kdc "$STATE"
chmod 0700 "$STATE"

cat >/etc/krb5.conf <<CONF
[libdefaults]
	default_realm = ${REALM}
	dns_lookup_kdc = false
	dns_lookup_realm = false
	rdns = false

[realms]
	${REALM} = {
		kdc = localhost
		admin_server = localhost
		database_module = directory
	}

[domain_realm]
	.heracles.test = ${REALM}
	heracles.test = ${REALM}

[dbdefaults]
	ldap_kerberos_container_dn = ${CONTAINER_DN}

[dbmodules]
	directory = {
		db_library = kldap
		ldap_servers = ${LDAP_URI}
		ldap_kdc_dn = ${LDAP_ADMIN_DN}
		ldap_kadmind_dn = ${LDAP_ADMIN_DN}
		ldap_service_password_file = ${KEYFILE}
		ldap_conns_per_server = 5
	}
CONF

cat >/etc/krb5kdc/kdc.conf <<CONF
[kdcdefaults]
	kdc_ports = 88
	kdc_tcp_ports = 88

[realms]
	${REALM} = {
		database_module = directory
		acl_file = /etc/krb5kdc/kadm5.acl
		key_stash_file = ${STASH}
		max_life = 10h 0m 0s
		max_renewable_life = 7d 0h 0m 0s
		# no ticket without pre-authentication (no offline guessing of the reply)
		default_principal_flags = +preauth
	}
CONF

echo "*/admin@${REALM} *" >/etc/krb5kdc/kadm5.acl

ldap() {
	ldapsearch -x -H "$LDAP_URI" -D "$LDAP_ADMIN_DN" -w "$LDAP_ADMIN_PASSWORD" -LLL "$@"
}

echo "kdc: waiting for the directory at ${LDAP_URI}"
for _ in $(seq 1 60); do
	if ldap -s base -b "$BASE_DN" dn >/dev/null 2>&1; then
		break
	fi
	sleep 1
done
ldap -s base -b "$BASE_DN" dn >/dev/null

if ! ldap -o ldif-wrap=no -s base -b cn=Subschema objectClasses 2>/dev/null \
	| grep -q "NAME 'krbContainer'"; then
	echo "kdc: the directory has no Kerberos schema: run deploy/ldap/fetch-third-party.sh," >&2
	echo "kdc: then recreate the LDAP data volume (make dev-reset)" >&2
	exit 1
fi

# The KDC and the admin server bind to the directory with this password.
if [ ! -s "$KEYFILE" ]; then
	echo "kdc: storing the directory bind password"
	printf '%s\n%s\n' "$LDAP_ADMIN_PASSWORD" "$LDAP_ADMIN_PASSWORD" \
		| kdb5_ldap_util -D "$LDAP_ADMIN_DN" -w "$LDAP_ADMIN_PASSWORD" -H "$LDAP_URI" \
			stashsrvpw -f "$KEYFILE" "$LDAP_ADMIN_DN" >/dev/null
fi

realm_dn="cn=${REALM},${CONTAINER_DN}"
if ! ldap -s base -b "$realm_dn" dn 2>/dev/null | grep -q '^dn:'; then
	echo "kdc: creating the realm ${REALM} in the directory (first run)"
	kdb5_ldap_util -D "$LDAP_ADMIN_DN" -w "$LDAP_ADMIN_PASSWORD" -H "$LDAP_URI" \
		create -subtrees "$PEOPLE_DN" -sscope sub -r "$REALM" -s -P "$MASTER_PASSWORD" >/dev/null
	first_run=yes
elif [ ! -s "$STASH" ]; then
	echo "kdc: rebuilding the master key stash"
	printf '%s\n' "$MASTER_PASSWORD" | kdb5_util -r "$REALM" stash -f "$STASH" >/dev/null
	first_run=no
else
	first_run=no
fi

if [ "$first_run" = yes ]; then
	for item in $USERS; do
		name="${item%%:*}"
		rest="${item#*:}"
		password="${rest%%:*}"
		rdn="${rest#*:}"
		link=()
		if [ -n "$rdn" ] && ldap -s base -b "${rdn},${PEOPLE_DN}" dn 2>/dev/null | grep -q '^dn:'; then
			link=(-x "dn=${rdn},${PEOPLE_DN}")
		fi
		echo "kdc: principal ${name}@${REALM}${link:+ (linked to ${rdn},${PEOPLE_DN})}"
		kadmin.local -q "addprinc -pw ${password} ${link[*]} ${name}" >/dev/null
	done
	echo "kdc: principal admin/admin@${REALM}"
	kadmin.local -q "addprinc -pw ${ADMIN_PASSWORD} admin/admin" >/dev/null
	for service in $SERVICES; do
		echo "kdc: service principal ${service}@${REALM}"
		kadmin.local -q "addprinc -randkey ${service}" >/dev/null
	done
fi

echo "kdc: starting the admin server and the KDC for ${REALM}"
kadmind
exec krb5kdc -n

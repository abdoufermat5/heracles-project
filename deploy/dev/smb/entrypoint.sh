#!/bin/bash
# Start the dev SMB server against the dev directory.
#
# Bootstraps what the directory cannot provide by itself:
#   * the SMB domain entry (sambaDomain) the passdb backend reads, created only
#     when missing (the seed of a fresh volume already carries it);
#   * the password the server uses to manage accounts in the directory
#     (stored in its own secrets database);
#   * the machine-account container.
set -euo pipefail

LDAP_URI="${LDAP_URI:-ldap://ldap:1389}"
BASE_DN="${BASE_DN:-dc=heracles,dc=test}"
LDAP_ADMIN_DN="${LDAP_ADMIN_DN:-cn=admin,${BASE_DN}}"
LDAP_ADMIN_PASSWORD="${LDAP_ADMIN_PASSWORD:-admin}"
SMB_DOMAIN="${SMB_DOMAIN:-HERACLES}"
SMB_DOMAIN_SID="${SMB_DOMAIN_SID:-S-1-5-21-2738473741-1357294590-3500904181}"

ldap() {
	ldapsearch -x -H "$LDAP_URI" -D "$LDAP_ADMIN_DN" -w "$LDAP_ADMIN_PASSWORD" -LLL "$@"
}

echo "smb: waiting for the directory at ${LDAP_URI}"
for _ in $(seq 1 60); do
	if ldap -s base -b "$BASE_DN" dn >/dev/null 2>&1; then
		break
	fi
	sleep 1
done
ldap -s base -b "$BASE_DN" dn >/dev/null

# The passdb backend reads the domain policy and the RID counters from here.
domain_dn="sambaDomainName=${SMB_DOMAIN},${BASE_DN}"
if ! ldap -s base -b "$domain_dn" dn 2>/dev/null | grep -q '^dn:'; then
	echo "smb: creating the SMB domain entry ${domain_dn}"
	ldapadd -x -H "$LDAP_URI" -D "$LDAP_ADMIN_DN" -w "$LDAP_ADMIN_PASSWORD" <<-LDIF
		dn: ${domain_dn}
		objectClass: top
		objectClass: sambaDomain
		sambaDomainName: ${SMB_DOMAIN}
		sambaSID: ${SMB_DOMAIN_SID}
		sambaAlgorithmicRidBase: 1000
		sambaNextRid: 1000
		sambaNextUserRid: 1000
		sambaNextGroupRid: 1001
		sambaMinPwdLength: 5
		sambaPwdHistoryLength: 0
		sambaLogonToChgPwd: 0
		sambaMaxPwdAge: -1
		sambaMinPwdAge: 0
		sambaLockoutDuration: 30
		sambaLockoutObservationWindow: 30
		sambaLockoutThreshold: 0
		sambaForceLogoff: -1
		sambaRefuseMachinePwdChange: 0
	LDIF
fi

# Machine trust accounts are created below this container on a domain join.
machine_dn="ou=computers,${BASE_DN}"
if ! ldap -s base -b "$machine_dn" dn 2>/dev/null | grep -q '^dn:'; then
	echo "smb: creating ${machine_dn}"
	ldapadd -x -H "$LDAP_URI" -D "$LDAP_ADMIN_DN" -w "$LDAP_ADMIN_PASSWORD" <<-LDIF
		dn: ${machine_dn}
		objectClass: organizationalUnit
		ou: computers
	LDIF
fi

# The server stores the directory password it manages accounts with in its own
# secrets database (the smb.conf ldap admin dn).
echo "smb: storing the directory bind password in secrets.tdb"
smbpasswd -w "$LDAP_ADMIN_PASSWORD" >/dev/null

# Unix accounts of the directory through NSS: the server resolves the user
# entries it authenticates as posixAccount records.
echo "smb: starting nslcd (NSS against the directory)"
nslcd

echo "smb: starting smbd"
exec smbd --foreground --no-process-group --debug-stdout

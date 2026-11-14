# Dev SMB server whose accounts come from the dev directory (LDAP passdb).
#
# The account data is the standard SMB schema loaded by the test directory
# (deploy/ldap/schema/12-smb.ldif): the server authenticates with
# sambaNTPassword and reads sambaSID/sambaAcctFlags/sambaPrimaryGroupSID.
FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        samba samba-common-bin smbclient ldap-utils procps libnss-ldapd nslcd \
    && rm -rf /var/lib/apt/lists/*

COPY smb.conf /etc/samba/smb.conf
COPY nsswitch.conf /etc/nsswitch.conf
COPY nslcd.conf /etc/nslcd.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod 0755 /usr/local/bin/entrypoint.sh \
    && chmod 0600 /etc/nslcd.conf \
    && mkdir -p /srv/smb/shared \
    && chmod 0777 /srv/smb/shared

EXPOSE 445/tcp
VOLUME ["/srv/smb/shared"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

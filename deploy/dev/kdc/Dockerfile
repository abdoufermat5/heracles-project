# Dev Kerberos KDC whose principals live in the dev directory (LDAP database backend).
#
# The principal data is the standard Kerberos LDAP schema loaded by the test directory
# (deploy/ldap/schema/07-kerberos.ldif, fetched by deploy/ldap/fetch-third-party.sh): the
# Kerberos tab of Heracles edits the same principal entries the KDC serves tickets from.
FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        krb5-kdc krb5-admin-server krb5-kdc-ldap krb5-user ldap-utils procps \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

EXPOSE 88/tcp 88/udp 749/tcp
# Master key stash and directory bind password of the KDC.
VOLUME ["/var/lib/krb5kdc"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

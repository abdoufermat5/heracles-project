# Dev FTP server whose accounts come from the dev directory.
#
# Accounts are the standard FTP LDAP schema loaded by the test directory
# (deploy/ldap/schema/13-ftp.ldif): the server looks up posixAccount
# entries with FTPStatus enabled and binds with their password.
FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        pure-ftpd-ldap ldap-utils lftp procps \
    && rm -rf /var/lib/apt/lists/*

COPY pureftpd-ldap.conf /etc/pure-ftpd/db/heracles-ldap.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod 0755 /usr/local/bin/entrypoint.sh \
    && chmod 0600 /etc/pure-ftpd/db/heracles-ldap.conf \
    && mkdir -p /srv/ftp \
    && chmod 0777 /srv/ftp

# Publishes the control port and a small passive range (loopback-only on the host).
EXPOSE 21/tcp 30000-30009/tcp
VOLUME ["/srv/ftp"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

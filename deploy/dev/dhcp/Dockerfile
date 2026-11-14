# Dev DHCP server that serves the configuration stored in the dev directory
# (standard DHCP LDAP schema, deploy/ldap/schema/14-dhcp.ldif).
#
# The server package has no directory backend: the entrypoint renders the
# dhcpd.conf from the dhcpService subtree (render-dhcpd-conf) and serves it on
# the isolated compose network only.
FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        isc-dhcp-server ldap-utils python3 iproute2 procps \
    && rm -rf /var/lib/apt/lists/*

COPY render.py /usr/local/bin/render-dhcpd-conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod 0755 /usr/local/bin/render-dhcpd-conf /usr/local/bin/entrypoint.sh \
    && mkdir -p /run/heracles-dhcp \
    && touch /var/lib/dhcp/dhcpd.leases

EXPOSE 67/udp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

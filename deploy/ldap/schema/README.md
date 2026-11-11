# LDAP schemas

* `heracles.ldif` / `heracles.schema` — the Heracles schema (`cn=config` LDIF and
  OpenLDAP `.schema` form). They are generated from
  `backend/src/heracles/schema/definitions.py`; regenerate them with `make schema`
  and never edit them by hand. OIDs live under the permanent arc
  `2.25.147659383274657253636041013514546701909` (`.1.*` attribute types,
  `.2.*` objectClasses).
* Third-party schemas needed by some plugins (`sudo`, `openssh-lpk`, `dnszone`,
  `samba`, `kerberos`, `dhcp`, ...) come from those projects and are not
  distributed here (git-ignored). Copy their `cn=config` LDIF files into this
  directory, or convert `.schema` files with
  `make third-party-schema SCHEMAS="/path/sudo.schema ..."`. Prefix them with a number
  so they load before `heracles.ldif`.

The test server (`deploy/docker-compose.yml`) loads every `*.ldif` of this directory
at the first start of its data volume: run `make e2e-down` after changing them.

## Migrating an existing directory

Directories written by the older management tool use a different schema. Convert
them offline:

1. Export the directory: `slapcat -b <base> > old.ldif`.
2. Convert it: `heracles migrate-directory old.ldif new.ldif --report renames.csv`.
   Fix any reported error (unknown legacy names) and run it again; `--force` writes
   the output anyway.
3. On a fresh server, load the third-party schemas and `heracles.ldif`, then import:
   `slapadd -b <base> -l new.ldif`.
4. Scripts using API v1 must switch to the new attribute names: `renames.csv` lists
   every old → new pair found in the directory.

SOGo resources: point SOGo's `KindFieldName` to `hrcResourceKind` and
`MultipleBookingsFieldName` to `hrcResourceMultipleBookings`.

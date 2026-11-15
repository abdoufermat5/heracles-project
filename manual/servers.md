# Directory servers

Heracles speaks plain LDAPv3 and is tested in CI on every server of this matrix: the
python-ldap integration tests, the backend end-to-end tests and the browser tests
(`directory-servers` job; locally `make e2e` and `make e2e-ds`).

| Server | Tested version | Schema loading | Notes |
| --- | --- | --- | --- |
| OpenLDAP | 2.6 | `heracles schema export --format ldif` into `cn=config` (or `--format schema` with `slapd.conf`) | The reference server of the dev stack. |
| 389 Directory Server | latest container image | `heracles schema export --format ds`, copied into the instance's `schema/` directory (restart), or loaded online | Runs the same suites. |

## What every server needs

* **The Heracles schema** (`hrc*` definitions), reloaded at each upgrade. Definitions are only
  added between releases.
* The standard schemas `core`, `cosine`, `inetOrgPerson` and `nis` (`posixAccount`,
  `posixGroup`), and the schemas of the plugins you enable: the [plugins reference](plugins.md)
  lists the object classes each one needs. Some (sudo, SSH public keys, DNS zones, Kerberos, ...)
  come from their own projects and are not distributed with Heracles; a plugin whose classes are
  missing stays off.
* A **service account** that can read the whole managed subtree and write where Heracles
  manages entries. Heracles applies its own access rules (roles and ACL assignments) on top;
  the server's access control only has to let the service account through.
* **Paged results** (RFC 2696) for large listings. Heracles also works when a server answers a
  paged search of a missing entry with an empty success (389 Directory Server does): it checks the
  base entry in that case.
* Password changes: Heracles writes `userPassword` hashes itself.
  A password-policy overlay or plugin is optional; the `ppolicy` plugin reads and edits the
  policies.

## OpenLDAP

```sh
heracles schema export --format ldif -o heracles.ldif
ldapadd -Y EXTERNAL -H ldapi:/// -f heracles.ldif          # first load
```

To upgrade an existing `cn={N}heracles,cn=schema,cn=config` entry, replace its
`olcAttributeTypes` and `olcObjectClasses` with those of the new file (`ldapmodify`), or load the
new file on a fresh server and import the data with `slapadd`.

## 389 Directory Server

```sh
heracles schema export --format ds -o 99heracles.ldif
cp 99heracles.ldif /etc/dirsrv/slapd-<instance>/schema/ && dsctl <instance> restart
```

Or online, without a restart: `deploy/ldap/ldif2ds.py` turns the `cn=config` files of
`deploy/ldap/schema` into `ldapmodify` records on `cn=schema`, skipping the definitions the
server already has (389 Directory Server ships some standard schemas, sudo among them).
`deploy/ds/setup.sh` builds the test directory this way.

The service account can be a regular entry with an ACI granting it read and write on the
managed suffix; do not use `cn=Directory Manager` outside tests.

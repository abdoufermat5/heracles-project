# Changelog

Generated from the commit history by `scripts/changelog.py` ([Conventional Commits](https://www.conventionalcommits.org/)); versions follow the [versioning policy](manual/versioning.md).

## Unreleased

### Features

- **auth:** OpenID Connect groups mapped to directory roles held by the session (f8ecfb8d)

### Fixes

- **tasks:** notifications and extractor honour the author's rights and the central secret list (35524563)
- **secrets:** refuse pasted private keys and recognise more secret names (811ed6c6)
- **schema:** declare service secrets as secrets (ca03ccc1)
- **triggers:** run only approved scripts, never a shell, for administrators who just signed in (21fceb16)
- **auth:** end sessions and API tokens when the account is locked, deleted or its password changes (0bed19c0)
- **snapshots:** authorise a restore attribute by attribute and bound decompression (414223d6)
- **smb_accounts:** lock internal SMB attributes, reserve administrative RIDs and make logins unique directory-wide (a6873edb)
- **posix:** check id uniqueness before writing and make a refused update leave nothing behind (d7936284)
- **objects:** refuse caller values for readonly fields at creation and keep the service inside its base DN (00217c4c)
- **invitations:** give sending its own limiter and settings (b74b1985)
- **invitations:** require the sender's rights on the form and limit sending (8738e212)
- **automatic_groups:** run a task with the rights of its author (6ff539d2)
- **access:** bind administrators to their API token cap, refuse permanent grants, ignore expired memberships (849f3fbc)
- **auth:** keep login blocks through table eviction and limit spraying (060f8961)
- **api:** trust forwarded headers only through login.trusted_proxies (19411680)
- **ldapmanager:** full rights on the whole directory may import privileged content (b11c0bb2)
- **objects:** a move is judged by the tabs like an edit of the department (7df8d95a)
- **ldapmanager:** close audit, tokens and administrator entries to raw LDIF import (1658d38a)
- **deploy:** decode base64 LDIF values, drop unsafe DHCP values (b6f036bb)
- **autofs5:** refuse executable maps and '..' segments (9eed3cc6)
- **dhcp:** accept only plain statements and options (f2c897b6)
- **public_forms:** a form acts with the rights of its author, grants nothing, has a global name (c86dea96)
- **auth:** read the login methods, CAS and header settings from YAML only (0721106a)
- **acl:** an ACL change reaches every session at once (ce446942)
- **acl:** grant only rights the caller may grant, role template changes included (b855703c)
- **acl:** exclude service accounts from role filters and role occupant lookups (dd5060ab)
- **ldap:** enforce RDN boundary in dn.is_descendant (371b1389)
- **auth:** a service account is never a mapped role; role kept through the second factor (9f6efbaf)
- **auth:** refuse a role mapping DN that a YAML flow list split at its commas (01abbfe9)

### Tests

- restore the process-wide YAML configuration defaults after each test (b03fbda4)
- **e2e:** clean up role mapping leftovers of an interrupted run (5d98ab3a)
- **e2e:** provider group mapped to a directory role for the session (28559d21)

### Build

- **helm:** chart version and appVersion follow the package version (84f65f04)

### Continuous integration

- fail the backend job when a test fails behind the log pipe (fb82d716)
- **release:** gate publishing on the CI jobs, version check and image scan (c3229119)
- run the PostgreSQL tests, audit locked dependencies, test two replicas (cdddea64)
- **release:** script that fails when tag, backend, frontend and chart versions disagree (e8b0e653)

## v0.1.0-rc.1 — 2026-11-16

First public release. It brings the web console and the self-service portal for LDAP directories (users, groups, roles, departments, delegated administration with roles and ACLs), the Heracles LDAP schema, the plugins listed in manual/plugins.md, API v2 and API v1 compatibility, SCIM 2.0 provisioning, scoped API tokens, the tamper-evident audit log, access requests, time-bound grants and access reviews, backup and restore, and the Kubernetes chart. Changes are listed commit by commit from the next release on.

### Features

- **auth:** OpenID Connect sign-in, opt-in (roadmap R5) (280685f6)
- **tokens:** API tokens for service accounts (9c46bed3)
- **tokens:** optional network allow-list per token (ba5a4c50)
- **tokens:** rules for the plugin routes (562c51f9)
- **migrate:** dry-run report and post-migration checks (31bdbbba)
- **ldap:** 389 Directory Server in the support matrix (377be2a9)

### Fixes

- **auth:** OpenID Connect review follow-ups (8a371cd6)
- **storage:** list the oidc component for backups and database copies (121aec6c)
- **auth:** CAS and trusted-header sign-in refuse locked accounts (6c9a0de3)
- **tokens:** administrator shortcuts honour the token scope (02a2aa91)
- **deploy:** bundle the DNS zone schema so a fresh clone starts the OpenLDAP stack (a6bddced)
- **frontend:** initial bundle back under budget (a4d49ba7)
- **release:** changelog starts at a baseline; manual check in a fresh interpreter (ef996639)

### Performance

- **objects:** read a large listing light, then the page rows in full (ad6c7570)
- **objects:** bulk edit loads each object once and reads the locks once (473608d0)
- **objects:** count group members with one search per page (2090dec8)

### Documentation

- **manual:** the test stacks bundle the DNS zone schema (36d04652)
- **manual:** the directory indexes Heracles needs, with the sign-in numbers (7c05640d)
- **manual:** installation, upgrade, backup, versioning, generated configuration and plugins reference (61c41793)

### Refactoring

- **objects:** read the bulk edit's lock table inside the error handler (51831133)

### Tests

- **e2e:** OpenID Connect sign-in against a real provider (b4e34d1a)
- **e2e:** service-account tokens in the browser, on the real stacks (c89007c2)
- **bench:** baseline after the groups counter and bulk edit changes (ed586cc1)

### Build

- **release:** 0.1.0-rc.1 (7219b26b)
- **release:** AGPL licence, contributor and security policies, generated changelog, tagged releases (9a07300d)

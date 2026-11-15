# Versioning policy

Heracles follows [Semantic Versioning 2.0](https://semver.org/): `MAJOR.MINOR.PATCH`.

* **PATCH**: bug and security fixes, no new configuration and no new schema.
* **MINOR**: new features, new configuration keys, new schema definitions, new app-database
  migrations; everything that worked keeps working.
* **MAJOR**: a breaking change (below). While the version is `0.y.z`, a breaking change raises
  the **minor** number and is listed first in the changelog.

## What counts as breaking

| Contract | Breaking | Not breaking |
| --- | --- | --- |
| API v2 (`/api/v2`, `docs` spec) | removing or renaming a route, field or error code; changing a field's type or meaning; a stricter validation of a previously accepted request | new routes, new optional request fields, new response fields, new error codes on new routes |
| API v1 compatibility layer | any change in its behaviour | — |
| Configuration file | removing or renaming a key, changing a default in a way that changes behaviour | new keys with defaults keeping the old behaviour |
| `hrc` LDAP schema | removing or changing a definition (OIDs are never reused or renumbered) | new attribute types and object classes; new `MAY` attributes on an existing class |
| Application database | a migration that cannot run automatically, or loses data | new migrations (applied automatically at start) |
| CLI | removing a command or option, changing an exit code | new commands and options |

Breaking changes are announced with `!` in the commit type and a `BREAKING CHANGE:` footer, so
they appear at the top of the changelog and of the upgrade notes.

## Deprecation

A feature, route, configuration key or option is **deprecated** for at least one minor release
(and at least three months) before it is removed: it keeps working, the changelog and the
upgrade guide say so, and Heracles logs a `deprecated` warning when it is used.

## Downgrades

App-database migrations only go forward: a server refuses to start on a database migrated by a
newer version, and `heracles restore` refuses an archive from a newer version. To go back,
restore the backup taken before the upgrade.

## Support

| Version | Security fixes | Bug fixes |
| --- | --- | --- |
| below 1.0 | latest minor | latest minor |
| 1.0 and later | latest and previous minor | latest minor |

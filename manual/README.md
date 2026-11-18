# Heracles manual

Administrator documentation for Heracles, a web console for LDAP directories.

| Page | What it covers |
| --- | --- |
| [Installation](install.md) | Containers, Kubernetes, the Python package, loading the LDAP schema |
| [Directory servers](servers.md) | Supported LDAP servers and what each needs |
| [Configuration reference](configuration.md) | Every setting of `heracles.yaml` (generated) |
| [Settings of the `api` section](settings.md) | Every key of the `api:` block with its default and meaning |
| [Plugins reference](plugins.md) | What each plugin adds and the schema it needs (generated) |
| [Upgrading](upgrade.md) | The upgrade procedure and per-release notes |
| [Backup and restore](backup.md) | `heracles backup` / `heracles restore` |
| [Migrating a legacy directory](migration.md) | Converting an existing directory to the Heracles schema |
| [Versioning policy](versioning.md) | Semantic versions, what is breaking, deprecations, support |
| [Security](../SECURITY.md) | Reporting a vulnerability, supported versions |

The [changelog](../CHANGELOG.md) lists the changes of each release.

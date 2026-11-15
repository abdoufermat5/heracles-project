# Backup and restore

`heracles backup` and `heracles restore` save and reload what Heracles keeps **outside** the
directory: the application database (second factors, API tokens, access requests and reviews,
task history, plugin switches, ...) and the configuration file. The directory stays the source of
truth for the objects; an LDIF export of the managed subtree can be added. No external tool
(`pg_dump`, `sqlite3`) is needed, and an archive restores on either database backend.

```
heracles backup  [--config heracles.yaml] -o backup.tar.gz [--ldif] [--directory ID] [--exclude-secrets]
heracles restore backup.tar.gz [--config heracles.yaml] [--ldif] [--directory ID] [--force]
```

## Backing up

* The database is the one the server would open with `--config` (or `$HERACLES_CONFIG`;
  `$HERACLES_DATABASE_URL` wins). The server keeps running: the tables are read in one
  transaction, so the archive is a consistent snapshot.
* `--ldif` adds every entry under the base DN of a directory (`--directory`, default the first).
* The archive holds password hashes (with `--ldif`), second-factor seeds, API token hashes and the
  configuration with its secrets: store it like the directory itself. `--exclude-secrets` blanks
  the secrets of the archived configuration (keys ending in `password`, `secret`, `token`, ...).
  Secrets given through the environment or files are never in the archive.
* The archive is a `tar.gz` with a `manifest.json` (format version, Heracles version, schema
  version of each database component, SHA-256 of every file), one JSON-lines file per table, the
  configuration file and the optional LDIF. Sessions and other short-lived state are left out.

## Restoring

```sh
# stop the web replicas and the worker; point heracles.yaml at the new, empty database
heracles restore backup.tar.gz --config heracles.yaml
# start them again: everyone signs in again (sessions are not restored)
```

Restore rules:

1. Every file is checked against the manifest (hash, size, no extra or unsafe member) before
   anything is written.
2. An archive from a **newer** release is refused (format or database component newer than this
   release knows): upgrade Heracles first. An **older** archive is loaded at its own schema
   version, then migrated.
3. A target database holding data is refused unless `--force`, which replaces all of it.
4. The database part is one transaction: on error nothing is changed.
5. `--ldif` adds the entries missing from the directory (parents first). Existing entries are
   reported and left alone; nothing is ever modified or deleted. Re-running is safe.

The archived configuration is not applied by `restore`; extract it with
`tar xzf backup.tar.gz config/` when you need it.

## On Kubernetes

Run the commands from a pod (`kubectl exec deploy/heracles-worker -- heracles backup ...`) or a
Job using the same image, ConfigMap and Secret, and copy the archive out. The LDIF export does
not replace the directory server's own backup for large directories.

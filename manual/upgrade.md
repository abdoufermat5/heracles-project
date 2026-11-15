# Upgrading

Heracles follows [semantic versioning](versioning.md). Read the release notes (and the
**Breaking changes** section of the [changelog](../CHANGELOG.md)) of every version between yours
and the target.

## Procedure

1. **Back up**: `heracles backup --config heracles.yaml -o before-<version>.tar.gz` (see
   [Backup and restore](backup.md)); also back up the directory with its own tools.
2. **Load the new schema** into the directory before starting the new version:
   `heracles schema export` from the new release, loaded as in [Directory servers](servers.md).
   The schema only adds definitions; loading it while the old version runs is safe.
3. **Review the configuration**: new keys have defaults keeping the previous behaviour; renamed or
   removed keys are listed in the release notes. Deprecated keys still work and log a
   `deprecated` warning.
4. **Deploy the new version** (image tag, chart `image.tag`, or wheel). At start, each component
   of the application database runs its new migrations automatically. Several replicas may start
   together: the migrations are serialised.
5. **Check**: `heracles check`, sign in, and look at *Directory health* in the console.

## Going back

Migrations only go forward: an older version refuses to start on a database a newer version has
migrated, and `heracles restore` refuses archives from a newer version. To go back, stop the
replicas, restore the backup of step 1 into an empty database, and deploy the previous version.
Definitions added to the LDAP schema can stay: older versions ignore them.

## Release notes

Upgrade notes of each release are in its GitHub release and in the [changelog](../CHANGELOG.md).
Version 0.1.0 is the first release: there is nothing to upgrade from.

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

## Container user: UID/GID 10001

The image now runs as the fixed user `heracles` (UID and GID 10001); earlier images used a UID
chosen at build time (999 in the manifests). The Kubernetes manifests and the Helm chart set
`runAsUser`, `runAsGroup` and `fsGroup` to 10001. A volume created by an earlier release
(`/var/lib/heracles`, the application database) is still owned by the old UID: change its owner
once before, or while, starting the new version, or the pod cannot write its database.

* Kubernetes with a `fsGroup`: most storage drivers fix the ownership at mount time and nothing
  is needed; otherwise run once, for example as an init step or a one-off pod mounting the
  claim: `chown -R 10001:10001 /var/lib/heracles`.
* Docker or Compose: `docker run --rm -u 0 -v <volume>:/data <image> chown -R 10001:10001 /data`.
* A Helm release that overrides `podSecurityContext` keeps its values: set them to 10001 too.

## Graceful shutdown

On SIGTERM `heracles serve` makes `/readyz` answer 503 and keeps serving for
`HERACLES_DRAIN_SECONDS` (or `--drain-seconds`; default 5, 0 stops at once), then finishes the
requests in flight and stops. The web Deployment of the manifests and of the chart also has a
`preStop` sleep of 15 seconds and `terminationGracePeriodSeconds: 60`; if you change the drain
period or the readiness probe period, keep the grace period above `preStop + drain + 30`.
`heracles worker` stops after the task it is running on SIGTERM.

## Going back

Migrations only go forward: an older version refuses to start on a database a newer version has
migrated, and `heracles restore` refuses archives from a newer version. To go back, stop the
replicas, restore the backup of step 1 into an empty database, and deploy the previous version.
Definitions added to the LDAP schema can stay: older versions ignore them.

## Release notes

Upgrade notes of each release are in its GitHub release and in the [changelog](../CHANGELOG.md).
Version 0.1.0 is the first release: there is nothing to upgrade from.

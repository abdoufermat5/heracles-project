# Installation

Heracles runs next to your LDAP server. It needs:

* an LDAP server with the **Heracles schema** loaded (below) and a service account that may read
  and write the managed subtree;
* a place for its **application database**: a SQLite file (one host) or PostgreSQL (several
  replicas or hosts);
* a TLS-terminating reverse proxy in front of the console for anything but a trial.

## Container image (recommended)

Release images are published as `ghcr.io/abdoufermat5/heracles:<version>` for `linux/amd64` and
`linux/arm64`, signed with cosign (keyless) and shipped with an SBOM and a provenance
attestation. Check the signature before deploying:

```sh
cosign verify ghcr.io/abdoufermat5/heracles:<version> \
  --certificate-identity-regexp '^https://github.com/abdoufermat5/heracles-project/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

### Docker Compose

`deploy/production/compose.yml` runs the console with its data volume. It builds the image from
the checkout; to run a release instead, replace its `build:` section with
`image: ghcr.io/abdoufermat5/heracles:<version>`.

```sh
docker compose -f deploy/production/compose.yml up -d
docker compose -f deploy/production/compose.yml logs heracles   # prints the setup token
```

Open `http://localhost:8420` and paste the token. Without a configuration file Heracles starts in
**setup mode**: it asks for the directory (testing the connection and the schema), the first
administrator and the plugins, writes the configuration to the data volume and switches to normal
mode without a restart. `heracles init` asks the same questions in a terminal. To write the file by
hand, start from the [configuration reference](configuration.md).

The image runs `heracles serve --with-worker`: the web console plus the task scheduler
(reminders, expirations, audit retention, ...). With several processes, keep one scheduler, or run
`heracles worker` separately: a lease in the database makes extra schedulers harmless.

### Kubernetes

`deploy/helm/heracles/` is a Helm chart and `deploy/kubernetes/` the same objects as plain
manifests (`kubectl apply -k deploy/kubernetes`): web replicas, one worker, readiness on
`/readyz` and liveness on `/healthz`, secrets mounted as files, PostgreSQL external. See
[`deploy/helm/heracles/README.md`](../deploy/helm/heracles/README.md).

## Python package

Each release also publishes a wheel (with its SBOM and attestation). It contains the server, the
worker and the CLI; the web console's static files are built from `frontend/` (`pnpm build`) and
served with `heracles serve --static DIR`.

```sh
pip install 'heracles-<version>-py3-none-any.whl[ldap,postgres]'   # python-ldap needs libldap and libsasl headers
heracles --version
heracles serve --config /etc/heracles/heracles.yaml --with-worker
```

## Loading the LDAP schema

Heracles stores its own objects with the `hrc*` schema (OIDs under
`2.25.147659383274657253636041013514546701909`). Export it for your server:

```sh
heracles schema export --format ldif   -o heracles.ldif     # OpenLDAP, cn=config
heracles schema export --format schema -o heracles.schema   # OpenLDAP, slapd.conf
heracles schema export --format ds     -o 99heracles.ldif   # 389 Directory Server
```

Load it as described in [Directory servers](servers.md). The schema only grows between releases
(see the [versioning policy](versioning.md)); reload it at each upgrade.

## First checks

```sh
heracles check --config heracles.yaml          # directory health checks (exit 1 on errors)
heracles audit verify --config heracles.yaml   # the audit log hash chain, once in use
```

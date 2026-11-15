# Heracles on Kubernetes

Two equivalent ways to run Heracles on a cluster: this Helm chart, and the plain manifests of
`deploy/kubernetes/` (`kubectl apply -k deploy/kubernetes`). Both create:

| Object | What it runs |
| --- | --- |
| `heracles-web` Deployment (2 replicas) | `heracles serve`, without the scheduler. Readiness `/readyz` (directory and database reachable), liveness `/healthz` (the process only), so a directory outage makes pods unready instead of restarting them. On SIGTERM `/readyz` turns 503 and in-flight requests finish. |
| `heracles-worker` Deployment (1 replica) | `heracles worker`: reminders, expirations, audit purge, ... A lease in the database makes extra replicas harmless. |
| `heracles` Service | port 8420 to the web pods. |
| `heracles` ConfigMap | `heracles.yaml`, mounted at `/etc/heracles/heracles.yaml`. |
| Ingress (optional) | Off by default (`ingress.enabled`). |

State lives in an **external PostgreSQL** (sessions, login throttling, task lease, access
requests, ...): the web replicas and the worker only share it through the database, so SQLite is
not an option here. The directory is your LDAP server.

## Secrets

The chart never stores a secret. Create one Secret and name it in `secrets.existingSecret`:

```sh
kubectl create secret generic heracles-secrets \
  --from-file=bind_password=./bind_password \
  --from-literal=database_url='postgresql://heracles:CHANGE_ME@postgres:5432/heracles'
```

* Every key is mounted as a read-only file in `/etc/heracles/secrets`. The configuration points
  at them with the `*_file` keys: `directories[].bind_password_file` and `mail.password_file`
  (a trailing newline is removed).
* `database_url` (key name: `secrets.databaseUrl.key`; Secret: `secrets.databaseUrl.existingSecret`,
  default the one above) is passed as `$HERACLES_DATABASE_URL`.
* A changed ConfigMap rolls the pods (checksum annotation); a changed Secret does not: run
  `kubectl rollout restart deployment/<release>-web deployment/<release>-worker`.

## Install

```sh
docker build -f deploy/Dockerfile -t REGISTRY/heracles:0.1.0 . && docker push REGISTRY/heracles:0.1.0
helm install heracles deploy/helm/heracles \
  --set image.repository=REGISTRY/heracles --set image.tag=0.1.0 \
  --set secrets.existingSecret=heracles-secrets \
  -f my-values.yaml
```

`my-values.yaml` sets `config:` (the content of `heracles.yaml`, see
`deploy/production/heracles.example.yaml`: directory URI, `base_dn`, `bind_dn`, `admin_dns`,
`allowed_hosts`, plugins), `web.replicas`, `web.resources`, `worker.resources` and, with an
ingress controller, `ingress.*`. TLS ends at the ingress: list the controller's pod network
under `config.api.login.trusted_proxies` so client addresses and the secure cookie are right.
For a trial over plain http through `kubectl port-forward`, set
`config.api.session.cookie_secure: false`.

Pods run as the image's unprivileged user (uid 999) with a read-only root file system, no
capabilities and the `RuntimeDefault` seccomp profile.

## Upgrade

Migrations of the application database only go forward and run at start-up. Roll out the new
image with `helm upgrade --set image.tag=...`: the web Deployment replaces pods one at a time
(`maxUnavailable: 0`), each new pod joining the Service once `/readyz` answers 200. Set
`HERACLES_BUILD_ID` identically when you build the frontend and the image (the Dockerfile
build argument `HERACLES_BUILD_ID`).

## Checks

```sh
helm lint deploy/helm/heracles -f deploy/helm/heracles/ci/test-values.yaml
helm template heracles deploy/helm/heracles -f deploy/helm/heracles/ci/test-values.yaml \
  | kubectl apply --dry-run=client -f -
kubectl apply --dry-run=client -k deploy/kubernetes
```

The `kubernetes` job of `.github/workflows/ci.yml` goes further on a kind cluster: it builds the
image, loads it into the cluster, starts PostgreSQL and a seeded OpenLDAP
(`ci/backing-services.yaml`, data from `deploy/ldap`), installs the chart with
`ci/kind-values.yaml`, waits for both Deployments and requires `/readyz` to answer 200.

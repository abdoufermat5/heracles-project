# Settings of the `api` section

Every key of the `api:` block of `heracles.yaml`, with its default. The
[configuration reference](configuration.md) shows a commented example file; this page
lists the whole set, section by section. Keys you leave out keep the default shown.
Durations are in the unit given in the key name.

## Top level

| Key | Default | Meaning |
| --- | --- | --- |
| `directory_labels` | `{}` | Names shown in the directory selector, as `id: label`. A directory without an entry shows its id. |
| `admin_dns` | `[]` | DNs of the accounts that bypass the access rules (bootstrap administrators). |
| `allowed_hosts` | `localhost`, `127.0.0.1`, `[::1]`, `testserver` | Host names the console may build links from (invitations, CAS) when no public address is configured. `*.example.org` matches subdomains. Set it in production. |
| `max_body_bytes` | `10485760` (10 MiB) | Largest request body of any endpoint (413 above), counted while the body is read. |
| `max_import_body_bytes` | `33554432` (32 MiB) | Larger limit for the import endpoints, whose documents arrive JSON-escaped (the handlers cap LDIF at 10 MiB and CSV at 5 MiB). |
| `import_paths` | `/ldif/import`, `/csv/parse`, `/csv/import` | The endpoints that use `max_import_body_bytes`. |
| `static_dir` | unset | Directory of the built console, served when it exists. The container image finds it by itself. |
| `enable_docs` | `false` | Serve the interactive API documentation. |
| `totp_issuer` | `Heracles` | Issuer name shown in authenticator apps. |

## `session`

| Key | Default | Meaning |
| --- | --- | --- |
| `cookie_name` | `heracles_session` | Name of the session cookie. |
| `cookie_secure` | `true` | Send the cookie over HTTPS only. Set `false` only when you serve plain HTTP (trials). |
| `idle_timeout_seconds` | `1800` | A session with no activity for this long ends. |
| `absolute_timeout_seconds` | `43200` (12 hours) | A session ends this long after sign-in, whatever its activity. |

## `login`

| Key | Default | Meaning |
| --- | --- | --- |
| `login_attribute` | `uid` | Attribute people sign in with. |
| `user_object_class` | `inetOrgPerson` | Object class of the entries that may sign in. |
| `header_enabled` | `false` | Trust a login name sent in an HTTP header by a reverse proxy. |
| `header_name` | `AUTH_USER` | The header read when `header_enabled` is on. |
| `trusted_proxies` | `[]` | Addresses or CIDRs of the reverse proxies. Only a listed peer is believed when it sends `X-Forwarded-For` or `X-Forwarded-Proto`, which the client address of the throttling, the audit log and HSTS rely on. |
| `free_attempts` | `5` | Failed sign-ins tolerated before a delay applies. |
| `base_delay_seconds` | `2.0` | First delay after the free attempts. |
| `max_delay_seconds` | `900.0` | Longest delay. |
| `ip_free_attempts` | `300` | Failures tolerated per hour from one address, all logins together, before the same delay applies to that address. `0` turns this aggregate off. |
| `login_free_attempts` | `30` | Failures tolerated per hour against one login, all addresses together, before the same delay applies to that login. `0` turns this aggregate off. |
| `max_second_factor_failures` | `5` | Wrong second-factor codes tolerated before the pending sign-in is dropped. |

## `recovery`

Password recovery by mail. It needs the `mail:` section.

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Offer password recovery. |
| `ttl_minutes` | `10` | How long the link in the mail stays valid. |
| `base_url` | `http://localhost:8000` | Absolute URL of the console, used to build the link. Set your public address. |
| `mail_attribute` | `mail` | Attribute holding the address the mail is sent to. |
| `subject` | `Password recovery` | Subject of the mail. |
| `body` | built-in text | Body of the mail. `{login}`, `{minutes}` and `{link}` are replaced. |

## `password`

| Key | Default | Meaning |
| --- | --- | --- |
| `min_length` | `8` | Shortest password accepted. |
| `min_differing` | `0` | Distinct characters a password must contain (`0`: no rule). |
| `default_method` | `ssha` | Hash used for new passwords. |
| `allowed_methods` | `ssha`, `ssha512`, `argon2`, `crypt/sha-512`, `crypt/sha-256`, `crypt/blowfish` | Hashes the console accepts. |
| `force_default` | `false` | Always hash with `default_method`. |

## `api_tokens`

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Allow API tokens (`Authorization: Bearer hrc_...`). |
| `max_lifetime_days` | `365` | Longest lifetime a token may be given (at least 1); every token expires. |
| `max_per_owner` | `20` | Tokens one person may hold at once (at least 1). |

## `scim`

SCIM 2.0 provisioning at `/scim/v2`, with API tokens only.

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Turn the endpoint on. |
| `user_base` | `""` | Department DN where new users are created (empty: the directory base). |
| `group_base` | `""` | Department DN where new groups are created (empty: the directory base). |
| `id_attribute` | `entryUUID` | Operational attribute holding the stable resource `id`. |
| `user_attributes` | `{}` | Extra SCIM path to LDAP attribute mappings, merged over the built-in ones. Keys are lower-cased SCIM paths such as `title`. |
| `max_results` | `200` | Largest page of a list request (at least 1). |

The built-in user mappings are `userName` to `uid`, `name.familyName` to `sn`,
`name.givenName` to `givenName`, `name.formatted` to `cn`, `displayName` to `displayName`,
`preferredLanguage` to `preferredLanguage`, `userType` to `employeeType`, and the enterprise
extension's `employeeNumber`, `organization` and `department` to `employeeNumber`, `o` and
`ou`.

## `webauthn`

Security keys and passkeys as a second factor.

| Key | Default | Meaning |
| --- | --- | --- |
| `rp_id` | `localhost` | Relying party identifier: the public host name of the console, without scheme or port. |
| `rp_name` | `Heracles` | Name of the relying party. |
| `origin` | `http://localhost:8000` | Exact origin people use in their browser, with scheme and port. |

## `database`

| Key | Default | Meaning |
| --- | --- | --- |
| `path` | unset | SQLite file of the application database. Unset: in memory (demo, tests); the production server uses `$HERACLES_DATA_DIR/heracles.db`. |
| `url` | unset | `postgresql://user:password@host/db`: a PostgreSQL database shared by replicas on several hosts (needs the `postgres` extra). Wins over `path`; `$HERACLES_DATABASE_URL` wins over the file. |

## `plugins`

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | unset | Plugin names to enable, or `["*"]` for all. Absent: the core profile. A plugin also needs its object classes in the directory schema. Choices made in the console are stored in the database and win over this list. |

## `metrics`

The Prometheus endpoint; it answers 404 unless enabled.

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Serve the metrics. |
| `allowed_networks` | `[]` | CIDRs allowed to scrape. Empty: any client, so protect the endpoint at the proxy. |

## `branding`

| Key | Default | Meaning |
| --- | --- | --- |
| `organization` | `""` | Organisation name on the sign-in page. |
| `logo_url` | `""` | Logo, as an absolute URL or a path under the served console. Empty: the product mark. |
| `tagline` | `""` | One line under the name on the sign-in page. |

## `triggers`

| Key | Default | Meaning |
| --- | --- | --- |
| `scripts_dir` | unset | Directory of the executables a trigger may name, by bare file name (no shell is involved). Unset: triggers are off. Keep the directory owned by root and not writable by the service user. |

## `sso`

Login methods, read from this file only: the directory entry that older versions used
for them is never consulted, so editing it cannot redirect sign-in.

| Key | Default | Meaning |
| --- | --- | --- |
| `login_method` | `form` | One of `form`, `http-basic`, `http-header`, `cas`. |
| `http_auth_enabled` | `false` | Accept HTTP Basic credentials besides the form. |
| `http_header_auth_enabled` | `false` | Accept a login name sent in a header by a trusted proxy. |
| `http_header_name` | `AUTH_USER` | The header read for it. |
| `cas_enabled` | `false` | Offer CAS sign-in (it also needs `cas_host`). |
| `cas_host` | `""` | Host name of the CAS server. |
| `cas_port` | `443` | Its port. |
| `cas_context` | `/cas` | Path of the CAS application on that host. |
| `cas_ca_cert_path` | `""` | CA bundle to verify the CAS server. |
| `cas_verbose` | `false` | Verbose CAS logging. |
| `cas_service_name` | `""` | Public URL or host name of the console as the CAS server sees it. |

## `oidc`

OpenID Connect sign-in (authorization code with PKCE), read from this file only. The
password form stays available as the fallback.

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Turn it on. Then `issuer` (an http or https URL) and `client_id` are required, and a client secret unless `client_auth` is `none`. |
| `issuer` | `""` | Issuer URL; its discovery document must state the same issuer. |
| `client_id` | `""` | Client identifier registered at the provider. |
| `client_secret` | `""` | Client secret. Not together with `client_secret_file`. |
| `client_secret_file` | `""` | Read the secret from this file. |
| `client_auth` | `client_secret_basic` | `client_secret_basic`, `client_secret_post` or `none` (public client). |
| `scopes` | `openid`, `profile`, `email` | Scopes requested; `openid` is added when missing. |
| `claim` | `preferred_username` | ID token claim naming the person. Pick one people cannot change at the provider. |
| `attribute` | `""` | Directory attribute the claim must equal (empty: the login attribute). |
| `label` | `""` | Text after "Sign in with" on the button (empty: a generic text). |
| `allowed_groups` | `[]` | When set, the token must carry one of these values in `groups_claim`. |
| `groups_claim` | `groups` | Claim holding the person's groups. |
| `role_mapping` | `{}` | Value of `groups_claim` to a list of directory role DNs held for that session only, on top of the roles the person has in the directory. Write one DN per `- ` line: a `[..]` list would split a DN at its commas. |
| `public_url` | `""` | Public address of the console, where the provider redirects to (`<public_url>/api/v2/auth/oidc/callback`). Empty: derived as for CAS. |
| `ca_cert_path` | `""` | CA bundle to verify the provider (empty: the system store). |

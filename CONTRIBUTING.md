# Contributing to Heracles

Thank you for helping. Heracles is licensed under the
[GNU Affero General Public License v3.0 or later](LICENSE) (`AGPL-3.0-or-later`).

## Contributor terms

Contributions are accepted under the same licence, with the
[Developer Certificate of Origin](https://developercertificate.org/) (DCO 1.1): by adding a
`Signed-off-by:` line to each commit you certify that you wrote the change, or otherwise have the
right to submit it under the project licence.

```
git commit -s -m "fix(acl): ..."
```

No copyright assignment is asked for; you keep the copyright of your contribution.

## Ground rules

* **Clean room.** Implement from the project's own specifications. Do not read, copy or port
  code from other directory management products, and do not name them in code, comments,
  documentation, UI strings or commits.
* **Schema.** Heracles' LDAP schema lives in `backend/src/heracles/schema/definitions.py`:
  append only, never renumber or reuse an OID. Export it with `make schema`.
* **Commits** follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat(acl): …`, `fix(api): …`, `docs: …`); the changelog is generated from them. Mark a
  breaking change with `!` (`feat(api)!: …`) and a `BREAKING CHANGE:` footer, following the
  [versioning policy](manual/versioning.md).
* Keep changes small and focused, with tests.

## Checks

Backend (from `backend/`): `uv sync`, `uv run pytest`, `uv run ruff check .`,
`uv run ruff format --check .`, `uv run pyright`.

Frontend (from `frontend/`): `pnpm install`, `pnpm test`, `pnpm lint`, `pnpm build`.

End to end: `make e2e` (OpenLDAP) and `make e2e-ds` (389 Directory Server).

## Reporting security issues

Never in a public issue: see [SECURITY.md](SECURITY.md).

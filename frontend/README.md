# Heracles frontend

Single-page web console for Heracles. React 19, TypeScript (strict), Vite,
Tailwind CSS v4, shadcn/ui (Radix primitives), TanStack Query / Router / Table,
react-hook-form + zod, react-i18next (en, fr), MSW for the mocked API.

The contract with the backend is the API v2; the types live in
`src/api/types.ts` and must be kept in sync with it.

## Commands

```bash
pnpm install
pnpm dev          # mocked API by default (VITE_API_MOCK=true in dev)
pnpm test --run   # vitest (jsdom + MSW)
pnpm lint
pnpm build
```

Run against a real backend: `VITE_API_MOCK=false pnpm dev`. Requests to `/api`
are proxied to `http://localhost:8000`.

### Mock backend

`src/mocks/` implements every API v2 endpoint over an in-memory dataset
(about 200 users, groups, roles, departments, DNS zones; `posix` is an optional
tab on `user`). Demo logins (any non-empty password except `wrong`):

| Login    | Behaviour                                                  |
| -------- | ---------------------------------------------------------- |
| `admin`  | full rights                                                |
| `viewer` | read-only ACL, password attribute hidden                   |
| `mfa`    | requires a second factor: TOTP `123456`, recovery `RECOVERY-0001` |

The second user in the list is edit-locked by someone else, to exercise the
409 dialog. The recovery link token `valid-token` is accepted by the mock.

## Structure

```
src/
  api/          types.ts (contract), client.ts (fetch wrapper, CSRF, errors),
                endpoints.ts, hooks.ts (TanStack Query)
  components/
    ui/         shadcn components
    fields/     one component per attribute kind + FieldInput dispatcher
    shell/      app shell, sidebar, command palette
  features/     auth, dashboard, listing, editor, me
  lib/          form helpers (diff, ACL), validation, theme, scope, icons
  locales/      en.ts, fr.ts (fr is typed against en: no missing keys)
  mocks/        MSW handlers + in-memory db + type definitions
  router.tsx    code-based routes, auth guard
```

## Design tokens

Colours, radii and fonts are CSS variables in `src/index.css`, exposed to
Tailwind through `@theme`. There is one accent colour (`--primary`); light and
dark palettes are defined side by side. The theme follows the system by
default and can be toggled from the top bar or the user menu.

## Notes on behaviour

* Mutations send `X-CSRF-Token` fetched from `GET /auth/csrf`; a 401 on any
  request sends the user to the login page.
* The editor sends only changed attributes in `PATCH`. A `department` attribute
  named `base` is handled as a move (`POST .../move`).
* Attribute rights come from the `acl` block of the object response: `""`
  hides the field, `"r"` makes it read-only, `"rw"` editable.
* Server validation errors (`fields`, keyed `tab.attr[.sub]`) are mapped onto
  the matching fields and the first failing tab is selected.

## API contract gaps found

See the hand-off notes of the frontend stream; the main ones are password
recovery endpoints, a global search endpoint, list/composite error key format,
the meaning of absent attributes in `acl`, and snapshot payload shapes.

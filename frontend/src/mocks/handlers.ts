import { http, HttpResponse, delay, type HttpHandler } from 'msw'
import type { ErrorCode, ObjectListItem, TabState } from '@/api/types'
import { BASE_DN, db } from './db'
import { ioHandlers } from './io'
import { typeSummaries } from './typeDefs'

const B = '/api/v2'
const SESSION_KEY = 'heracles.mock.session'

function persist(): void {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(db.session))
  } catch {
    /* not available (tests) */
  }
}

export function restoreMockSession(): void {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (raw) db.session = JSON.parse(raw) as typeof db.session
  } catch {
    /* ignore */
  }
}

function err(
  status: number,
  code: ErrorCode,
  message: string,
  extra: Record<string, unknown> = {},
) {
  return HttpResponse.json({ error: { code, message, ...extra } }, { status })
}

const unauth = () => err(401, 'unauthenticated', 'Authentication required')

function csrfOk(request: Request): boolean {
  return request.headers.get('X-CSRF-Token') === db.csrf
}

/** Wrap a handler with session + CSRF checks. */
function guarded<T extends { request: Request; params: Record<string, string | readonly string[] | undefined> }>(
  fn: (info: T) => Response | Promise<Response>,
  opts: { mutation?: boolean } = {},
) {
  return async (info: T): Promise<Response> => {
    if (!db.me()) return unauth()
    if (opts.mutation && !csrfOk(info.request)) return err(403, 'forbidden', 'Invalid CSRF token')
    return fn(info)
  }
}

const dnParam = (p: string | readonly string[] | undefined): string =>
  decodeURIComponent(Array.isArray(p) ? (p[0] ?? '') : String(p ?? ''))

function inScope(dn: string, base: string, scope: string): boolean {
  const d = dn.toLowerCase()
  const b = base.toLowerCase()
  if (!d.endsWith(b)) return false
  if (scope === 'sub') return true
  // 'one': object lives directly in a container directly under `base`
  const rest = d.slice(0, d.length - b.length).replace(/,$/, '')
  const parts = rest.split(',')
  return parts.length <= 2
}

export const handlers: HttpHandler[] = [
  http.get(`${B}/auth/csrf`, () => HttpResponse.json({ token: db.csrf })),
  http.get(`${B}/directories`, () => HttpResponse.json(db.directories())),

  http.post(`${B}/auth/login`, async ({ request }) => {
    if (!csrfOk(request)) return err(403, 'forbidden', 'Invalid CSRF token')
    const body = (await request.json()) as { username: string; password: string }
    await delay(150)
    if (!body.username || !body.password || body.password === 'wrong')
      return err(401, 'unauthenticated', 'Invalid credentials')
    if (body.username === 'mfa') {
      db.session = { user: null, pending: 'mfa' }
      persist()
      return HttpResponse.json({ status: 'second_factor', methods: ['totp', 'recovery'] })
    }
    db.session = { user: body.username, pending: null }
    persist()
    return HttpResponse.json({ status: 'ok' })
  }),

  http.post(`${B}/auth/second-factor`, async ({ request }) => {
    if (!csrfOk(request)) return err(403, 'forbidden', 'Invalid CSRF token')
    if (!db.session.pending) return unauth()
    const body = (await request.json()) as { method: string; code: string }
    const good = body.method === 'totp' ? '123456' : 'RECOVERY-0001'
    if (body.code !== good) return err(401, 'unauthenticated', 'Invalid code')
    db.session = { user: 'mfa', pending: null }
    persist()
    return HttpResponse.json({ status: 'ok' })
  }),

  http.post(`${B}/auth/logout`, ({ request }) => {
    if (!csrfOk(request)) return err(403, 'forbidden', 'Invalid CSRF token')
    db.session = { user: null, pending: null }
    persist()
    return new HttpResponse(null, { status: 204 })
  }),

  http.get(`${B}/auth/me`, () => {
    const me = db.me()
    return me ? HttpResponse.json(me) : unauth()
  }),

  http.post(`${B}/auth/recovery`, async ({ request }) => {
    if (!csrfOk(request)) return err(403, 'forbidden', 'Invalid CSRF token')
    return new HttpResponse(null, { status: 202 })
  }),

  http.post(`${B}/auth/recovery/confirm`, async ({ request }) => {
    if (!csrfOk(request)) return err(403, 'forbidden', 'Invalid CSRF token')
    const body = (await request.json()) as { login: string; token: string; password: string }
    if (!db.recoveryTokens.has(body.token)) return err(422, 'validation', 'Invalid or expired link')
    if (body.password.length < 8)
      return err(422, 'validation', 'Password too short', { fields: { password: 'At least 8 characters' } })
    return HttpResponse.json({ status: 'ok' })
  }),

  http.get(`${B}/types`, guarded(() => HttpResponse.json(typeSummaries))),

  http.get(
    `${B}/types/:type`,
    guarded(({ params }) => {
      const d = db.descriptor(String(params.type))
      return d ? HttpResponse.json(d) : err(404, 'not_found', 'Unknown type')
    }),
  ),

  http.get(`${B}/tree`, guarded(() => HttpResponse.json(db.tree()))),

  http.get(
    `${B}/dashboard`,
    guarded(() =>
      HttpResponse.json({
        cards: [
          { key: 'users', label: 'Users', value: db.all('user').length, trend: 4 },
          { key: 'groups', label: 'Groups', value: db.all('group').length, trend: 0 },
          { key: 'roles', label: 'Roles', value: db.all('role').length, trend: null },
          { key: 'departments', label: 'Departments', value: db.all('department').length + 1, trend: 1 },
          { key: 'dns_zones', label: 'DNS zones', value: db.all('dns_zone').length, trend: null },
        ],
        locked_users: db.all('user').filter((u) => u.accountLocked).length,
        expiring_passwords: 12,
        tasks: { pending: 2, failed: 0 },
      }),
    ),
  ),

  http.get(
    `${B}/objects/:type`,
    guarded(async ({ request, params }) => {
      const type = String(params.type)
      const desc = db.descriptor(type)
      if (!desc) return err(404, 'not_found', 'Unknown type')
      const u = new URL(request.url)
      const base = u.searchParams.get('base') || BASE_DN
      const scope = u.searchParams.get('scope') || 'sub'
      const q = (u.searchParams.get('q') ?? '').toLowerCase()
      const limit = Math.min(Number(u.searchParams.get('limit') ?? 50) || 50, 200)
      const sort = u.searchParams.get('sort')
      const order = u.searchParams.get('order') === 'desc' ? -1 : 1
      const offset = Number(atob(u.searchParams.get('cursor') ?? btoa('0'))) || 0

      const flat = (r: ReturnType<typeof db.all>[number]): Record<string, unknown> => {
        const v: Record<string, unknown> = {}
        for (const t of Object.values(r.tabs)) Object.assign(v, t.values)
        return v
      }
      let rows = db
        .all(type)
        .filter((r) => inScope(r.dn, base, scope))
        .map((r) => ({ r, v: flat(r) }))
      if (q)
        rows = rows.filter(
          ({ r, v }) =>
            r.dn.toLowerCase().includes(q) ||
            desc.columns.some((c) => String(v[c.key] ?? '').toLowerCase().includes(q)),
        )
      const key = sort ?? desc.main_attr
      rows.sort((a, b) =>
        String(a.v[key] ?? '').localeCompare(String(b.v[key] ?? ''), undefined, { numeric: true }) * order,
      )
      const page = rows.slice(offset, offset + limit)
      const items: ObjectListItem[] = page.map(({ r, v }) => ({
        dn: r.dn,
        values: Object.fromEntries(desc.columns.map((c) => [c.key, v[c.key] ?? null])),
        locked: r.accountLocked,
      }))
      const next = offset + limit < rows.length ? btoa(String(offset + limit)) : null
      await delay(120)
      return HttpResponse.json({ items, next_cursor: next, total: rows.length })
    }),
  ),

  http.post(
    `${B}/objects/:type`,
    guarded(
      async ({ request, params }) => {
        const type = String(params.type)
        const desc = db.descriptor(type)
        if (!desc) return err(404, 'not_found', 'Unknown type')
        if (db.isReadOnlySession()) return err(403, 'forbidden', 'Not allowed')
        const body = (await request.json()) as {
          base: string
          tabs: Record<string, TabState>
        }
        const errors = db.validate(desc, body.tabs)
        if (!body.base) errors['main.base'] = 'This field is required'
        if (Object.keys(errors).length)
          return err(422, 'validation', 'Validation failed', { fields: errors })
        const rec = db.create(type, body.base, body.tabs)
        return HttpResponse.json({ dn: rec.dn }, { status: 201 })
      },
      { mutation: true },
    ),
  ),

  http.get(
    `${B}/objects/:type/:dn`,
    guarded(({ params }) => {
      const rec = db.get(dnParam(params.dn))
      if (!rec || rec.type !== params.type) return err(404, 'not_found', 'Object not found')
      return HttpResponse.json(db.detail(rec))
    }),
  ),

  http.patch(
    `${B}/objects/:type/:dn`,
    guarded(
      async ({ request, params }) => {
        const rec = db.get(dnParam(params.dn))
        if (!rec || rec.type !== params.type) return err(404, 'not_found', 'Object not found')
        if (db.isReadOnlySession()) return err(403, 'forbidden', 'Not allowed')
        const desc = db.descriptor(rec.type)
        if (!desc) return err(404, 'not_found', 'Unknown type')
        const lock = db.locks.get(rec.dn.toLowerCase())
        if (lock && lock.user !== db.session.user) return err(409, 'locked', 'Object is locked', { lock })
        const body = (await request.json()) as {
          tabs: Record<string, { active: boolean; values: Record<string, unknown> }>
        }
        // validate the result of the merge
        const merged: Record<string, TabState> = {}
        for (const t of desc.tabs) {
          const cur = rec.tabs[t.name] ?? { active: false, values: {} }
          const ch = body.tabs[t.name]
          merged[t.name] = ch
            ? { active: ch.active, values: { ...cur.values, ...ch.values } }
            : { active: cur.active, values: { ...cur.values } }
        }
        const errors = db.validate(desc, merged, rec.dn)
        if (Object.keys(errors).length)
          return err(422, 'validation', 'Validation failed', { fields: errors })
        db.patch(rec, body.tabs)
        await delay(100)
        return HttpResponse.json(db.detail(rec))
      },
      { mutation: true },
    ),
  ),

  http.delete(
    `${B}/objects/:type/:dn`,
    guarded(
      ({ params }) => {
        const rec = db.get(dnParam(params.dn))
        if (!rec || rec.type !== params.type) return err(404, 'not_found', 'Object not found')
        if (db.isReadOnlySession()) return err(403, 'forbidden', 'Not allowed')
        db.remove(rec.dn)
        return new HttpResponse(null, { status: 204 })
      },
      { mutation: true },
    ),
  ),

  http.post(
    `${B}/objects/:type/:dn/move`,
    guarded(
      async ({ request, params }) => {
        const rec = db.get(dnParam(params.dn))
        if (!rec) return err(404, 'not_found', 'Object not found')
        const { base } = (await request.json()) as { base: string }
        return HttpResponse.json({ dn: db.move(rec, base) })
      },
      { mutation: true },
    ),
  ),

  http.post(
    `${B}/objects/:type/:dn/lock`,
    guarded(
      ({ params }) => {
        const dn = dnParam(params.dn)
        const rec = db.get(dn)
        if (!rec) return err(404, 'not_found', 'Object not found')
        const key = rec.dn.toLowerCase()
        const cur = db.locks.get(key)
        if (cur && cur.user !== db.session.user)
          return err(409, 'locked', 'Object is locked by another user', { lock: cur })
        const lock = cur ?? { user: db.session.user ?? '', since: new Date().toISOString() }
        db.locks.set(key, lock)
        return HttpResponse.json({ lock })
      },
      { mutation: true },
    ),
  ),

  http.delete(
    `${B}/objects/:type/:dn/lock`,
    guarded(
      ({ params }) => {
        const key = dnParam(params.dn).toLowerCase()
        const cur = db.locks.get(key)
        if (cur && cur.user === db.session.user) db.locks.delete(key)
        return new HttpResponse(null, { status: 204 })
      },
      { mutation: true },
    ),
  ),

  http.post(
    `${B}/users/:dn/lock`,
    guarded(
      ({ params }) => {
        const rec = db.get(dnParam(params.dn))
        if (!rec) return err(404, 'not_found', 'Object not found')
        rec.accountLocked = true
        return new HttpResponse(null, { status: 204 })
      },
      { mutation: true },
    ),
  ),

  http.post(
    `${B}/users/:dn/unlock`,
    guarded(
      ({ params }) => {
        const rec = db.get(dnParam(params.dn))
        if (!rec) return err(404, 'not_found', 'Object not found')
        rec.accountLocked = false
        return new HttpResponse(null, { status: 204 })
      },
      { mutation: true },
    ),
  ),

  http.get(
    `${B}/objects/:type/:dn/snapshots`,
    guarded(({ params }) => {
      const dn = dnParam(params.dn).toLowerCase()
      const list = [...db.snapshots.values()]
        .filter((s) => s.dn.toLowerCase() === dn)
        .map(({ id, description, created_at }) => ({ id, description, created_at }))
      return HttpResponse.json(list)
    }),
  ),

  http.post(
    `${B}/objects/:type/:dn/snapshots`,
    guarded(
      async ({ request, params }) => {
        const body = (await request.json()) as { description?: string }
        const snap = {
          id: db.newId(),
          description: body.description ?? '',
          created_at: new Date().toISOString(),
          dn: dnParam(params.dn),
          type: String(params.type),
        }
        db.snapshots.set(snap.id, snap)
        return HttpResponse.json(
          { id: snap.id, description: snap.description, created_at: snap.created_at },
          { status: 201 },
        )
      },
      { mutation: true },
    ),
  ),

  http.post(
    `${B}/snapshots/:id/restore`,
    guarded(
      ({ params }) =>
        db.snapshots.has(String(params.id))
          ? new HttpResponse(null, { status: 204 })
          : err(404, 'not_found', 'Snapshot not found'),
      { mutation: true },
    ),
  ),

  http.delete(
    `${B}/snapshots/:id`,
    guarded(
      ({ params }) => {
        db.snapshots.delete(String(params.id))
        return new HttpResponse(null, { status: 204 })
      },
      { mutation: true },
    ),
  ),

  // --- P3 compat ---
  ...ioHandlers,
]

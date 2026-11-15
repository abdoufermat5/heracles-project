import { http, HttpResponse, delay, type HttpHandler } from 'msw'
import type { ApiTokenInfo, ErrorCode, ObjectListItem, TabState } from '@/api/types'
import { APP_VERSION } from '@/lib/appVersion'
import { BASE_DN, db } from './db'
import { adminHandlers } from './adminHandlers'
import { accessHandlers } from './accessHandlers'
import { auditHandlers } from './auditHandlers'
import { ioHandlers } from './io'
import { publicHandlers } from './publicHandlers'
import { attributesOf, FilterSyntaxError, ldapMatches, parseLdapFilter } from './ldapFilter'
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

/**
 * Length problem of a body string, worded like the server's model error
 * (`heracles.api.errors` renders the 422 `fields` of the login, second-factor, step-up and
 * recovery endpoints), or `null` when the server's cap accepts it.
 */
function lengthProblem(value: unknown, min: number, max: number): string | null {
  if (typeof value !== 'string') return 'Field required'
  if (value.length < min) return `String should have at least ${min} character${min === 1 ? '' : 's'}`
  if (value.length > max) return `String should have at most ${max} character${max === 1 ? '' : 's'}`
  return null
}

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
  http.get(`${B}/branding`, () =>
    HttpResponse.json({ organization: '', logo_url: null, tagline: '' }),
  ),

  http.get(`${B}/status`, () =>
    db.me()
      ? HttpResponse.json({
          directories: { main: { available: true, read_only: false } },
          version: APP_VERSION,
        })
      : unauth(),
  ),

  http.post(`${B}/auth/login`, async ({ request }) => {
    if (!csrfOk(request)) return err(403, 'forbidden', 'Invalid CSRF token')
    const body = (await request.json()) as { username: string; password: string }
    await delay(150)
    // the server's LoginBody: username 1..256, password at most 1024
    const fields: Record<string, string> = {}
    const username = lengthProblem(body.username, 1, 256)
    if (username) fields.username = username
    if (typeof body.password !== 'string') fields.password = 'Field required'
    else if (body.password.length > 1024) fields.password = 'String should have at most 1024 characters'
    if (Object.keys(fields).length) return err(422, 'validation', 'Invalid request', { fields })
    if (!body.username || !body.password || body.password === 'wrong')
      return err(401, 'unauthenticated', 'Invalid credentials')
    if (body.username === 'mfakey') {
      db.session = { user: null, pending: 'mfa' }
      persist()
      return HttpResponse.json({ status: 'second_factor', methods: ['webauthn', 'totp'] })
    }
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
    const body = (await request.json()) as {
      method: string
      code?: string
      credential?: { id?: string }
    }
    // SecondFactorBody: a known method, code at most 2048, a credential for WebAuthn
    const fields: Record<string, string> = {}
    if (body.method !== 'totp' && body.method !== 'webauthn' && body.method !== 'recovery')
      fields.method = 'Input should be totp, webauthn or recovery'
    const code = lengthProblem(body.code ?? '', 0, 2048)
    if (code) fields.code = code
    if (body.method === 'webauthn' && !body.credential) fields.credential = 'Field required'
    if (Object.keys(fields).length) return err(422, 'validation', 'Invalid request', { fields })
    if (body.method === 'webauthn') {
      if (body.credential?.id !== 'mock-assertion') return err(401, 'unauthenticated', 'Invalid code')
    } else {
      const good = body.method === 'totp' ? '123456' : 'RECOVERY-0001'
      if (body.code !== good) return err(401, 'unauthenticated', 'Invalid code')
    }
    db.session = { user: 'mfa', pending: null }
    persist()
    return HttpResponse.json({ status: 'ok' })
  }),

  http.post(`${B}/auth/webauthn/options`, ({ request }) => {
    if (!csrfOk(request)) return err(403, 'forbidden', 'Invalid CSRF token')
    if (!db.session.pending) return unauth()
    return HttpResponse.json({
      options: {
        challenge: 'Y2hhbGxlbmdl',
        rpId: 'localhost',
        allowCredentials: [{ id: 'a2V5', type: 'public-key' }],
      },
    })
  }),

  http.get(`${B}/auth/webauthn/credentials`, guarded(() => HttpResponse.json(db.securityKeys))),

  http.post(
    `${B}/auth/webauthn/credentials/options`,
    guarded(
      () =>
        !db.reauthFresh
          ? err(403, 'reauth_required', 'Confirm your password to continue')
          : HttpResponse.json({
              options: {
                challenge: 'Y2hhbGxlbmdl',
                rp: { id: 'localhost', name: 'Heracles' },
                user: { id: 'dXNlcg', name: 'admin', displayName: 'Admin' },
                pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
              },
            }),
      { mutation: true },
    ),
  ),

  http.post(
    `${B}/auth/webauthn/credentials`,
    guarded(
      async ({ request }) => {
        const body = (await request.json()) as { label?: string; credential?: unknown }
        // WebAuthnRegisterBody: optional label of at most 64 characters, a credential
        const fields: Record<string, string> = {}
        const label = lengthProblem(body.label ?? '', 0, 64)
        if (label) fields.label = label
        if (!body.credential) fields.credential = 'Field required'
        if (Object.keys(fields).length) return err(422, 'validation', 'Invalid request', { fields })
        const key = { id: `key-${db.securityKeys.length + 1}`, label: body.label ?? '', sign_count: 0 }
        db.securityKeys.push(key)
        return HttpResponse.json(key, { status: 201 })
      },
      { mutation: true },
    ),
  ),

  http.delete(
    `${B}/auth/webauthn/credentials/:id`,
    guarded(
      ({ params, request }) => {
        if (!db.reauthFresh) return err(403, 'reauth_required', 'Confirm your password to continue')
        const confirm = new URL(request.url).searchParams.get('confirm_disable') === 'true'
        const only = db.securityKeys.length === 1 ? db.securityKeys[0] : undefined
        if (only?.id === params.id && !confirm)
          return err(409, 'last_second_factor', 'Removing this key turns off the second factor')
        const before = db.securityKeys.length
        db.securityKeys = db.securityKeys.filter((k) => k.id !== params.id)
        return db.securityKeys.length === before
          ? err(404, 'not_found', 'Not found')
          : new HttpResponse(null, { status: 204 })
      },
      { mutation: true },
    ),
  ),

  http.get(
    `${B}/auth/totp`,
    guarded(() =>
      HttpResponse.json({
        enabled: db.totp.enabled,
        recovery_codes_remaining: db.totp.recoveryCodes,
        security_keys: db.securityKeys.length,
      }),
    ),
  ),

  http.post(
    `${B}/auth/totp/begin`,
    guarded(
      () => {
        if (!db.reauthFresh) return err(403, 'reauth_required', 'Confirm your password to continue')
        db.totp.pending = true
        return HttpResponse.json({
          secret: 'JBSWY3DPEHPK3PXP',
          uri: 'otpauth://totp/Heracles:admin?secret=JBSWY3DPEHPK3PXP&issuer=Heracles',
          expires_in: 300,
        })
      },
      { mutation: true },
    ),
  ),

  http.post(
    `${B}/auth/totp/confirm`,
    guarded(
      async ({ request }) => {
        if (!db.reauthFresh) return err(403, 'reauth_required', 'Confirm your password to continue')
        const body = (await request.json()) as { code: string }
        // TotpConfirmBody: 1..16 characters
        const problem = lengthProblem(body.code, 1, 16)
        if (problem) return err(422, 'validation', 'Invalid request', { fields: { code: problem } })
        if (!db.totp.pending)
          return err(422, 'validation', 'Start the setup again', {
            fields: { code: 'Setup expired, start again' },
          })
        if (body.code !== '123456')
          return err(422, 'validation', 'Wrong code', { fields: { code: 'Wrong code' } })
        db.totp.pending = false
        db.totp.enabled = true
        return HttpResponse.json({ status: 'ok' })
      },
      { mutation: true },
    ),
  ),

  http.delete(
    `${B}/auth/totp`,
    guarded(
      ({ request }) => {
        if (!db.reauthFresh) return err(403, 'reauth_required', 'Confirm your password to continue')
        if (!db.totp.enabled) return err(404, 'not_found', 'Not found')
        const confirm = new URL(request.url).searchParams.get('confirm_disable') === 'true'
        const last = db.securityKeys.length === 0
        if (last && !confirm)
          return err(409, 'last_second_factor', 'Disabling this turns off the second factor')
        db.totp.enabled = false
        if (last) db.totp.recoveryCodes = 0
        return new HttpResponse(null, { status: 204 })
      },
      { mutation: true },
    ),
  ),

  http.post(
    `${B}/auth/recovery-codes`,
    guarded(
      () => {
        if (!db.reauthFresh) return err(403, 'reauth_required', 'Confirm your password to continue')
        if (!db.totp.enabled && db.securityKeys.length === 0)
          return err(409, 'second_factor_required', 'Set up a second factor first')
        db.totp.recoveryCodes = 10
        return HttpResponse.json({
          codes: Array.from({ length: 10 }, (_, i) => `MOCKA-0000${i}`),
        })
      },
      { mutation: true },
    ),
  ),

  http.get(
    `${B}/auth/sessions`,
    guarded(() => {
      if (db.sessions.length === 0) {
        const now = Math.floor(Date.now() / 1000)
        db.sessions = [
          { id: 'cur', user_agent: 'Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0', ip: '192.0.2.10', created_at: now - 600, last_seen: now, current: true },
          { id: 'old', user_agent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1', ip: '198.51.100.7', created_at: now - 86400, last_seen: now - 3600, current: false },
        ]
      }
      return HttpResponse.json(db.sessions)
    }),
  ),

  http.post(
    `${B}/auth/sessions/revoke-others`,
    guarded(
      () => {
        const revoked = db.sessions.filter((s) => !s.current).length
        db.sessions = db.sessions.filter((s) => s.current)
        return HttpResponse.json({ revoked })
      },
      { mutation: true },
    ),
  ),

  http.delete(
    `${B}/auth/sessions/:id`,
    guarded(
      ({ params }) => {
        const id = String(params.id)
        const target = db.sessions.find((s) => s.id === id)
        if (!target) return err(404, 'not_found', 'Session not found')
        if (target.current) return err(422, 'validation', 'This is the current session')
        db.sessions = db.sessions.filter((s) => s.id !== id)
        return new HttpResponse(null, { status: 204 })
      },
      { mutation: true },
    ),
  ),

  http.delete(
    `${B}/users/:dn/sessions`,
    guarded(() => HttpResponse.json({ revoked: 1, tokens_revoked: 0 }), { mutation: true }),
  ),

  // --- API tokens (contract: backend heracles.api.v2.tokens) ---
  http.get(
    `${B}/auth/tokens/limits`,
    guarded(() => HttpResponse.json({ enabled: true, max_lifetime_days: 365, scopes: ['read', 'write', 'admin'] })),
  ),

  http.get(
    `${B}/auth/tokens`,
    guarded(() => {
      const me = (db.session.user ?? '').toLowerCase()
      return HttpResponse.json(db.apiTokens.filter((t) => t.owner_dn.toLowerCase() === me))
    }),
  ),

  http.post(
    `${B}/auth/tokens`,
    guarded(
      async ({ request }) => {
        const body = (await request.json()) as { name?: string; scope?: string; types?: string[]; expires_in_days?: number }
        const fields: Record<string, string> = {}
        const name = (body.name ?? '').trim()
        if (!name) fields.name = 'Give the token a name'
        if (!['read', 'write', 'admin'].includes(body.scope ?? '')) fields.scope = 'One of: read, write, admin'
        const types = body.types ?? []
        if (types.length > 0 && body.scope === 'admin') fields.types = 'An admin token cannot be limited to some types'
        const days = body.expires_in_days ?? 0
        if (days < 1 || days > 365) fields.expires_in_days = 'At most 365 days'
        if (Object.keys(fields).length > 0) return err(422, 'validation', 'Invalid token', { fields })
        if (!db.reauthFresh) return err(403, 'reauth_required', 'Confirm your password to continue')
        const now = Math.floor(Date.now() / 1000)
        const id = (db.nextId++).toString(16).padStart(16, '0')
        const token: ApiTokenInfo = {
          id,
          name,
          owner_dn: db.session.user ?? '',
          scope: body.scope as ApiTokenInfo['scope'],
          types: [...types].sort(),
          created_at: now,
          expires_at: now + days * 86400,
          last_used_at: null,
          last_used_ip: '',
        }
        db.apiTokens.push(token)
        return HttpResponse.json({ ...token, secret: `hrc_${id}_${'m'.repeat(43)}` }, { status: 201 })
      },
      { mutation: true },
    ),
  ),

  http.delete(
    `${B}/auth/tokens/:id`,
    guarded(
      ({ params }) => {
        const me = (db.session.user ?? '').toLowerCase()
        const target = db.apiTokens.find((t) => t.id === String(params.id) && t.owner_dn.toLowerCase() === me)
        if (!target) return err(404, 'not_found', 'Token not found')
        db.apiTokens = db.apiTokens.filter((t) => t !== target)
        return new HttpResponse(null, { status: 204 })
      },
      { mutation: true },
    ),
  ),

  http.get(
    `${B}/tokens`,
    guarded(({ request }) => {
      const owner = new URL(request.url).searchParams.get('owner')
      const found = owner ? db.apiTokens.filter((t) => t.owner_dn.toLowerCase() === owner.toLowerCase()) : db.apiTokens
      return HttpResponse.json(found)
    }),
  ),

  http.delete(
    `${B}/tokens/:id`,
    guarded(
      ({ params }) => {
        const target = db.apiTokens.find((t) => t.id === String(params.id))
        if (!target) return err(404, 'not_found', 'Token not found')
        if (!db.reauthFresh) return err(403, 'reauth_required', 'Confirm your password to continue')
        db.apiTokens = db.apiTokens.filter((t) => t !== target)
        return new HttpResponse(null, { status: 204 })
      },
      { mutation: true },
    ),
  ),

  http.post(
    `${B}/auth/reauth`,
    guarded(
      async ({ request }) => {
        const body = (await request.json()) as { password?: string; method?: string; code?: string }
        // ReauthBody: a password or a code (and its method) — empty is refused; the caps
        // are 1024 characters for the password and 64 for the code
        const fields: Record<string, string> = {}
        const password = typeof body.password === 'string' ? body.password : ''
        const code = typeof body.code === 'string' ? body.code : ''
        if (password.length > 1024) fields.password = 'String should have at most 1024 characters'
        if (code.length > 64) fields.code = 'String should have at most 64 characters'
        if (Object.keys(fields).length) return err(422, 'validation', 'Invalid request', { fields })
        if (password === '' && !(body.method && code))
          return err(422, 'validation', 'Enter your password', { fields: { password: 'Required' } })
        if (body.password === 'wrong' || body.code === '000000')
          return err(422, 'validation', 'Wrong password', {
            fields: { [body.method ? 'code' : 'password']: 'Wrong value' },
          })
        db.reauthFresh = true
        return HttpResponse.json({ status: 'ok' })
      },
      { mutation: true },
    ),
  ),

  http.post(`${B}/auth/logout`, ({ request }) => {
    if (!csrfOk(request)) return err(403, 'forbidden', 'Invalid CSRF token')
    db.session = { user: null, pending: null }
    persist()
    return new HttpResponse(null, { status: 204 })
  }),

  http.get(`${B}/auth/me/groups`, () => {
    const me = db.me()
    if (!me) return err(401, 'unauthenticated', 'Not signed in')
    const mine = [...db.records.values()]
      .filter((r) => r.type === 'group')
      .filter((r) => {
        const members = r.tabs.main?.values.member
        const list = Array.isArray(members) ? members : members ? [members] : []
        return list.some((m) => String(m).toLowerCase() === me.dn.toLowerCase())
      })
      .map((r) => ({
        dn: r.dn,
        name: String(r.tabs.main?.values.cn ?? r.dn),
        description: String(r.tabs.main?.values.description ?? ''),
      }))
    return HttpResponse.json(mine)
  }),

  http.get(`${B}/auth/me`, () => {
    const me = db.me()
    return me ? HttpResponse.json(me) : unauth()
  }),

  http.get(`${B}/auth/password-policy`, () => HttpResponse.json({ min_length: 8 })),

  http.post(`${B}/auth/recovery`, async ({ request }) => {
    if (!csrfOk(request)) return err(403, 'forbidden', 'Invalid CSRF token')
    const body = (await request.json()) as { email?: string }
    // RecoveryBody: at most 320 characters, then the address the endpoint accepts
    const tooLong = lengthProblem(body.email ?? '', 0, 320)
    if (tooLong) return err(422, 'validation', 'Invalid request', { fields: { email: tooLong } })
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test((body.email ?? '').trim()))
      return err(422, 'validation', 'Invalid address', { fields: { email: 'Enter a valid email address.' } })
    return new HttpResponse(null, { status: 202 })
  }),

  http.post(`${B}/auth/recovery/confirm`, async ({ request }) => {
    if (!csrfOk(request)) return err(403, 'forbidden', 'Invalid CSRF token')
    const body = (await request.json()) as { login: string; token: string; password: string }
    // RecoveryConfirmBody: login 1..256, token 1..512, password at most 1024
    const fields: Record<string, string> = {}
    for (const [key, value, max] of [
      ['login', body.login, 256],
      ['token', body.token, 512],
      ['password', body.password, 1024],
    ] as const) {
      const problem = lengthProblem(value, 1, max)
      if (problem) fields[key] = problem
    }
    if (Object.keys(fields).length) return err(422, 'validation', 'Invalid request', { fields })
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
          { key: 'user', label: 'Users', value: db.all('user').length, trend: 4 },
          { key: 'group', label: 'Groups', value: db.all('group').length, trend: 0 },
          { key: 'role', label: 'Roles', value: db.all('role').length, trend: null },
          { key: 'department', label: 'Departments', value: db.all('department').length + 1, trend: 1 },
          { key: 'dns_zone', label: 'DNS zones', value: db.all('dns_zone').length, trend: null },
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
      const offsetParam = u.searchParams.get('offset')
      const offset = offsetParam !== null ? Number(offsetParam) : Number(atob(u.searchParams.get('cursor') ?? btoa('0'))) || 0
      const flat = (r: ReturnType<typeof db.all>[number]): Record<string, unknown> => {
        const v: Record<string, unknown> = {}
        for (const t of Object.values(r.tabs)) Object.assign(v, t.values)
        return v
      }
      let rows = db
        .all(type)
        .filter((r) => inScope(r.dn, base, scope))
        .map((r) => ({ r, v: flat(r) }))
      const rawFilter = u.searchParams.get('filter')
      if (rawFilter) {
        try {
          const node = parseLdapFilter(rawFilter)
          const known = new Set(
            desc.tabs.flatMap((t) =>
              t.sections.flatMap((sec) => sec.attributes.map((a) => a.name.toLowerCase())),
            ),
          )
          for (const a of attributesOf(node)) {
            if (a.toLowerCase() !== 'objectclass' && !known.has(a.toLowerCase()))
              return err(400, 'validation', `The attribute '${a}' cannot be used in a filter`)
          }
          rows = rows.filter(({ v }) =>
            ldapMatches(node, (attr) => {
              const key = Object.keys(v).find((k) => k.toLowerCase() === attr.toLowerCase())
              const val = key ? v[key] : undefined
              return (Array.isArray(val) ? val : val == null || val === '' ? [] : [val]).map(String)
            }),
          )
        } catch (e) {
          if (e instanceof FilterSyntaxError)
            return err(400, 'validation', `Invalid filter: ${e.message}`)
          throw e
        }
      }
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
      const items: ObjectListItem[] = page.map(({ r, v }) => {
        let groupsCount = 0
        if (type === 'user') {
          const userDn = r.dn.toLowerCase()
          for (const rec of db.records.values()) {
            if (rec.type === 'group') {
              const member = (rec.tabs.main?.values.member as string[] | string | undefined) ?? []
              const members = Array.isArray(member) ? member : [member]
              if (members.some((m) => typeof m === 'string' && m.toLowerCase() === userDn)) {
                groupsCount++
              }
            }
          }
        }
        return {
          dn: r.dn,
          values: {
            ...Object.fromEntries(desc.columns.map((c) => [c.key, v[c.key] ?? null])),
            groups_count: groupsCount,
          },
          locked: r.accountLocked,
          groups_count: groupsCount,
        }
      })
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
        // Changing your own password: the server asks for a recent confirmation first
        // (`heracles.api.v2.objects.patch_object` -> `require_recent_auth`)
        const me = db.me()
        const ownPassword =
          me !== null &&
          rec.dn.toLowerCase() === me.dn.toLowerCase() &&
          Object.values(body.tabs).some((tab) => 'userPassword' in (tab.values ?? {}))
        if (ownPassword && !db.reauthFresh) {
          return err(403, 'reauth_required', 'Confirm your password to continue')
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

  // --- P3 admin ---
  ...adminHandlers,
  ...accessHandlers,
  ...auditHandlers,
  // --- P3 compat ---
  ...ioHandlers,
  ...publicHandlers,
]

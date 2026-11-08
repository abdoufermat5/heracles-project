/**
 * Mock API of the object-management extras (templates, copy, multiple edit,
 * references, deleted snapshots, LDIF). These handlers are registered BEFORE the
 * generic ones (see server.ts / browser.ts) because `/objects/:type/_bulk` would
 * otherwise be taken for an object DN.
 */
import { http, HttpResponse, type HttpHandler } from 'msw'
import type { ErrorCode, TabState, TypeDescriptor, Values } from '@/api/types'
import { allAttributes } from '@/lib/objects'
import { BASE_DN, db, type MockSnapshot, type MockTemplate } from './db'

const B = '/api/v2'

function err(status: number, code: ErrorCode, message: string, extra: Record<string, unknown> = {}) {
  return HttpResponse.json({ error: { code, message, ...extra } }, { status })
}

const dnParam = (p: string | readonly string[] | undefined): string =>
  decodeURIComponent(Array.isArray(p) ? (p[0] ?? '') : String(p ?? ''))

function session(request: Request, mutation: boolean): Response | null {
  if (!db.me()) return err(401, 'unauthenticated', 'Authentication required')
  if (mutation && request.headers.get('X-CSRF-Token') !== db.csrf) {
    return err(403, 'forbidden', 'Invalid CSRF token')
  }
  return null
}

function factorsOf(dn: string) {
  return db.secondFactors.get(dn.toLowerCase()) ?? { totp: false, security_keys: [], recovery_codes: 0 }
}

/** Session, rights (only the non-viewer mock users hold the second-factor right) and target checks. */
function factorAccess(request: Request, mutation: boolean, dn: string): Response | null {
  const denied = session(request, mutation)
  if (denied) return denied
  if (!db.me()?.is_admin) return err(403, 'forbidden', 'You cannot view the second factors of this account')
  const rec = db.get(dn)
  return rec?.type === 'user' ? null : err(404, 'not_found', 'User not found')
}

// ── masks (a small subset of the real language) ──────────────────────────

const MASK_RE = /%(?:([^%|]*)\|)?([A-Za-z][A-Za-z0-9]*)%/g

function referencedAttributes(texts: string[]): string[] {
  const out: string[] = []
  for (const text of texts) {
    for (const m of text.matchAll(MASK_RE)) {
      const attr = m[2]
      if (attr && !(m[1] ?? '').includes('c') && !out.includes(attr)) out.push(attr)
    }
  }
  return out
}

function applyModifiers(value: string, mods: string): string {
  let out = value
  for (const m of mods.matchAll(/([a-zA-Z])(?:\[([^\]]*)\])?/g)) {
    const code = m[1]
    const args = (m[2] ?? '').split(',')
    if (code === 'l') out = out.toLowerCase()
    else if (code === 'u') out = out.toUpperCase()
    else if (code === 's') out = out.substr(Number(args[0] ?? 0), Number(args[1] ?? out.length))
    else if (code === 'a') out = out.normalize('NFD').replace(/[̀-ͯ]/g, '')
  }
  return out
}

function resolveText(text: string, given: Record<string, string>): string {
  return text.replace(MASK_RE, (_all, mods: string | undefined, attr: string) =>
    applyModifiers(given[attr.toLowerCase()] ?? '', mods ?? ''),
  )
}

function textOf(v: unknown): string {
  if (Array.isArray(v)) return v.length > 0 ? textOf(v[0]) : ''
  return v === null || v === undefined ? '' : String(v)
}

/** Flat `attribute (lower case) -> text` of the values the user supplied. */
function givenValues(values: Record<string, Values>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const attrs of Object.values(values)) {
    for (const [k, v] of Object.entries(attrs)) {
      const t = textOf(v)
      if (t !== '') out[k.toLowerCase()] = t
    }
  }
  return out
}

function tabOf(desc: TypeDescriptor, attr: string): string | null {
  const lower = attr.toLowerCase()
  for (const tab of desc.tabs) {
    if (allAttributes(tab).some((a) => a.name.toLowerCase() === lower)) return tab.name
  }
  return null
}

function templateFields(desc: TypeDescriptor, tpl: MockTemplate): Record<string, string[]> {
  const defined = new Set<string>()
  const texts: string[] = []
  for (const tab of Object.values(tpl.tabs)) {
    for (const [k, v] of Object.entries(tab.values)) {
      defined.add(k.toLowerCase())
      texts.push(...(Array.isArray(v) ? v : [v]))
    }
  }
  const out: Record<string, string[]> = {}
  for (const attr of referencedAttributes(texts)) {
    if (defined.has(attr.toLowerCase())) continue
    const tab = tabOf(desc, attr) ?? desc.tabs[0]?.name ?? 'main'
    const real = desc.tabs
      .flatMap((t) => allAttributes(t))
      .find((a) => a.name.toLowerCase() === attr.toLowerCase())
    ;(out[tab] ??= []).push(real?.name ?? attr)
  }
  return out
}

function resolveTemplate(
  desc: TypeDescriptor,
  tpl: MockTemplate,
  supplied: Record<string, Values>,
): { tabs: Record<string, Values>; missing: string[] } {
  const given = givenValues(supplied)
  const missing = Object.values(templateFields(desc, tpl)).flat().filter((a) => !given[a.toLowerCase()])
  const tabs: Record<string, Values> = {}
  for (const [name, tab] of Object.entries(tpl.tabs)) {
    if (!tab.active) continue
    const vals: Values = {}
    for (const [k, v] of Object.entries(tab.values)) {
      vals[k] = Array.isArray(v) ? v.map((x) => resolveText(x, given)) : resolveText(v, given)
    }
    tabs[name] = vals
  }
  for (const [name, attrs] of Object.entries(supplied)) tabs[name] = { ...(tabs[name] ?? {}), ...attrs }
  return { tabs, missing }
}

function findTemplate(type: string, dn: string): MockTemplate | undefined {
  const tpl = db.templates.get(dn.toLowerCase())
  return tpl && tpl.type === type ? tpl : undefined
}

/** Demo data for the browser mock: a "staff" user template. */
export function seedDemoTemplates(): void {
  const dn = `cn=staff,ou=templates,ou=people,${BASE_DN}`
  db.templates.set(dn.toLowerCase(), {
    dn,
    name: 'staff',
    type: 'user',
    base: BASE_DN,
    tabs: {
      main: {
        active: true,
        values: {
          uid: '%s[0,1]l|givenName%%l|sn%',
          cn: '%givenName% %sn%',
          mail: '%s[0,1]l|givenName%%l|sn%@example.com',
          employeeType: 'employee',
        },
      },
    },
  })
}

// ── copy / bulk helpers ──────────────────────────────────────────────────

const UNIQUE = new Set(['uid', 'uidnumber', 'gidnumber', 'mail', 'employeenumber', 'macaddress', 'iphostnumber'])
const BULK_EXCLUDED = new Set(['image', 'file', 'composite', 'password', 'display', 'hidden', 'department'])

function emptyLike(v: unknown): boolean {
  return v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0)
}

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

// ── handlers ─────────────────────────────────────────────────────────────

const templateJson = (tpl: MockTemplate, desc: TypeDescriptor) => ({
  dn: tpl.dn,
  name: tpl.name,
  type: tpl.type,
  base: tpl.base,
  tabs: Object.fromEntries(
    desc.tabs.map((t) => [t.name, tpl.tabs[t.name] ?? { active: !t.optional && t.name === 'main', values: {} }]),
  ),
})

function mergeTabs(
  desc: TypeDescriptor,
  tpl: MockTemplate,
  incoming: Record<string, { active?: boolean; values?: Record<string, string | string[]> }>,
): void {
  for (const [name, change] of Object.entries(incoming)) {
    const tab = desc.tabs.find((t) => t.name === name)
    if (!tab) continue
    const cur = tpl.tabs[name] ?? { active: !tab.optional, values: {} }
    const active = change.active ?? cur.active
    const values: Record<string, string | string[]> = active ? { ...cur.values } : {}
    for (const [k, v] of Object.entries(change.values ?? {})) {
      if (v === '' || (Array.isArray(v) && v.length === 0)) delete values[k]
      else values[k] = v
    }
    tpl.tabs[name] = { active, values }
  }
}

export const objectsHandlers: HttpHandler[] = [
  http.get(`${B}/types/:type`, ({ params }) => {
    if (!db.me()) return err(401, 'unauthenticated', 'Authentication required')
    const d = db.descriptor(String(params.type))
    if (!d) return err(404, 'not_found', 'Unknown type')
    return HttpResponse.json({ ...d, supports_templates: d.name !== 'department' })
  }),

  // ── templates ──
  http.get(`${B}/types/:type/templates`, ({ request, params }) => {
    const denied = session(request, false)
    if (denied) return denied
    const type = String(params.type)
    const list = [...db.templates.values()]
      .filter((t) => t.type === type)
      .sort((a, b) => a.name.localeCompare(b.name))
      .map(({ dn, name, base }) => ({ dn, name, type, base }))
    return HttpResponse.json(list)
  }),

  http.post(`${B}/types/:type/templates`, async ({ request, params }) => {
    const denied = session(request, true)
    if (denied) return denied
    const type = String(params.type)
    const desc = db.descriptor(type)
    if (!desc) return err(404, 'not_found', 'Unknown type')
    const body = (await request.json()) as {
      name: string
      base: string
      tabs: Record<string, { active?: boolean; values?: Record<string, string | string[]> }>
    }
    const name = body.name.trim()
    if (!name) return err(422, 'validation', 'Validation failed', { fields: { name: 'This field is required.' } })
    const dn = `cn=${name},ou=templates,${db.dnFor(desc, body.base, { main: { active: true, values: {} } }).replace(/^[^,]*,/, '')}`
    if (db.templates.has(dn.toLowerCase())) return err(409, 'conflict', 'A template with this name already exists')
    const tpl: MockTemplate = { dn, name, type, base: body.base, tabs: {} }
    mergeTabs(desc, tpl, body.tabs)
    db.templates.set(dn.toLowerCase(), tpl)
    return HttpResponse.json(templateJson(tpl, desc), { status: 201 })
  }),

  http.get(`${B}/types/:type/templates/:dn/fields`, ({ request, params }) => {
    const denied = session(request, false)
    if (denied) return denied
    const desc = db.descriptor(String(params.type))
    const tpl = findTemplate(String(params.type), dnParam(params.dn))
    if (!desc || !tpl) return err(404, 'not_found', 'Template not found')
    return HttpResponse.json({ fields: templateFields(desc, tpl) })
  }),

  http.post(`${B}/types/:type/templates/:dn/preview`, async ({ request, params }) => {
    const denied = session(request, true)
    if (denied) return denied
    const desc = db.descriptor(String(params.type))
    const tpl = findTemplate(String(params.type), dnParam(params.dn))
    if (!desc || !tpl) return err(404, 'not_found', 'Template not found')
    const body = (await request.json()) as { values: Record<string, Values> }
    const { tabs, missing } = resolveTemplate(desc, tpl, body.values ?? {})
    if (missing.length > 0) {
      return err(422, 'validation', 'Validation failed', {
        fields: Object.fromEntries(missing.map((a) => [`${tabOf(desc, a) ?? 'main'}.${a}`, 'This field is required.'])),
      })
    }
    return HttpResponse.json({ tabs })
  }),

  http.get(`${B}/types/:type/templates/:dn`, ({ request, params }) => {
    const denied = session(request, false)
    if (denied) return denied
    const desc = db.descriptor(String(params.type))
    const tpl = findTemplate(String(params.type), dnParam(params.dn))
    if (!desc || !tpl) return err(404, 'not_found', 'Template not found')
    return HttpResponse.json(templateJson(tpl, desc))
  }),

  http.patch(`${B}/types/:type/templates/:dn`, async ({ request, params }) => {
    const denied = session(request, true)
    if (denied) return denied
    const desc = db.descriptor(String(params.type))
    const tpl = findTemplate(String(params.type), dnParam(params.dn))
    if (!desc || !tpl) return err(404, 'not_found', 'Template not found')
    const body = (await request.json()) as {
      name?: string
      tabs: Record<string, { active?: boolean; values?: Record<string, string | string[]> }>
    }
    mergeTabs(desc, tpl, body.tabs)
    if (body.name && body.name !== tpl.name) {
      db.templates.delete(tpl.dn.toLowerCase())
      tpl.dn = tpl.dn.replace(/^cn=[^,]*/, `cn=${body.name}`)
      tpl.name = body.name
      db.templates.set(tpl.dn.toLowerCase(), tpl)
    }
    return HttpResponse.json(templateJson(tpl, desc))
  }),

  http.delete(`${B}/types/:type/templates/:dn`, ({ request, params }) => {
    const denied = session(request, true)
    if (denied) return denied
    const tpl = findTemplate(String(params.type), dnParam(params.dn))
    if (!tpl) return err(404, 'not_found', 'Template not found')
    db.templates.delete(tpl.dn.toLowerCase())
    return new HttpResponse(null, { status: 204 })
  }),

  // ── create from a template (falls through to the generic handler otherwise) ──
  http.post(`${B}/objects/:type`, async ({ request, params }) => {
    const denied = session(request, true)
    if (denied) return denied
    const body = (await request.clone().json()) as {
      base: string
      template?: string | null
      tabs: Record<string, TabState>
    }
    if (!body.template) return undefined
    const type = String(params.type)
    const desc = db.descriptor(type)
    const tpl = findTemplate(type, body.template)
    if (!desc || !tpl) return err(404, 'not_found', 'Template not found')
    const supplied = Object.fromEntries(Object.entries(body.tabs).map(([k, v]) => [k, v.values]))
    const { tabs, missing } = resolveTemplate(desc, tpl, supplied)
    if (missing.length > 0) {
      return err(422, 'validation', 'Validation failed', {
        fields: Object.fromEntries(missing.map((a) => [`${tabOf(desc, a) ?? 'main'}.${a}`, 'This field is required.'])),
      })
    }
    const full: Record<string, TabState> = Object.fromEntries(
      Object.entries(tabs).map(([k, values]) => [k, { active: true, values }]),
    )
    if (full.main) full.main.values.base = body.base
    const errors = db.validate(desc, full)
    if (Object.keys(errors).length > 0) return err(422, 'validation', 'Validation failed', { fields: errors })
    return HttpResponse.json({ dn: db.create(type, body.base, full).dn }, { status: 201 })
  }),

  // ── copy ──
  http.post(`${B}/objects/:type/:dn/copy`, async ({ request, params }) => {
    const denied = session(request, true)
    if (denied) return denied
    const type = String(params.type)
    const desc = db.descriptor(type)
    const rec = db.get(dnParam(params.dn))
    if (!desc || !rec || rec.type !== type) return err(404, 'not_found', 'Object not found')
    if (db.isReadOnlySession()) return err(403, 'forbidden', 'Not allowed')
    const body = (await request.json()) as { base: string; values?: Record<string, Values> }
    const tabs: Record<string, TabState> = {}
    for (const tab of desc.tabs) {
      const src = rec.tabs[tab.name]
      if (!src?.active) {
        tabs[tab.name] = { active: !tab.optional, values: {} }
        continue
      }
      const values: Values = {}
      for (const a of allAttributes(tab)) {
        const lname = a.name.toLowerCase()
        if (['display', 'password', 'department'].includes(a.kind)) continue
        if (lname === 'uidnumber' || lname === 'gidnumber') {
          values[a.name] = 30000 + Number(db.newId()) // allocated like a new account
          continue
        }
        if (UNIQUE.has(lname) || a.name === desc.main_attr) continue
        if (a.name in src.values) values[a.name] = structuredClone(src.values[a.name])
      }
      tabs[tab.name] = { active: true, values }
    }
    for (const [name, attrs] of Object.entries(body.values ?? {})) {
      const t = (tabs[name] ??= { active: true, values: {} })
      Object.assign(t.values, attrs)
    }
    if (tabs.main) tabs.main.values.base = body.base
    const errors = db.validate(desc, tabs)
    if (!tabs.main?.values[desc.main_attr]) errors[`main.${desc.main_attr}`] = 'This field is required'
    if (Object.keys(errors).length > 0) return err(422, 'validation', 'Validation failed', { fields: errors })
    return HttpResponse.json({ dn: db.create(type, body.base, tabs).dn }, { status: 201 })
  }),

  // ── multiple edit ──
  http.post(`${B}/objects/:type/_bulk/attributes`, async ({ request, params }) => {
    const denied = session(request, true)
    if (denied) return denied
    const desc = db.descriptor(String(params.type))
    if (!desc) return err(404, 'not_found', 'Unknown type')
    const body = (await request.json()) as { dns: string[] }
    const recs = body.dns.map((d) => db.get(d))
    const attributes: Record<string, string[]> = {}
    for (const tab of desc.tabs) {
      if (!recs.every((r) => r?.tabs[tab.name]?.active)) continue
      const names = allAttributes(tab)
        .filter((a) => !BULK_EXCLUDED.has(a.kind) && !a.readonly && a.name !== desc.main_attr)
        .map((a) => a.name)
      if (names.length > 0) attributes[tab.name] = names
    }
    return HttpResponse.json({ attributes })
  }),

  http.patch(`${B}/objects/:type/_bulk`, async ({ request, params }) => {
    const denied = session(request, true)
    if (denied) return denied
    const type = String(params.type)
    const desc = db.descriptor(type)
    if (!desc) return err(404, 'not_found', 'Unknown type')
    const body = (await request.json()) as {
      dns: string[]
      changes: Record<string, Record<string, { op: 'set' | 'add' | 'remove' | 'clear'; value?: unknown }>>
    }
    const results = body.dns.map((dn) => {
      const rec = db.get(dn)
      if (!rec || rec.type !== type) return { dn, ok: false, code: 'not_found', error: 'Object not found.' }
      if (db.isReadOnlySession()) return { dn, ok: false, code: 'forbidden', error: 'Not allowed' }
      const lock = db.locks.get(rec.dn.toLowerCase())
      if (lock && lock.user !== db.session.user) {
        return { dn, ok: false, code: 'locked', error: 'Being edited by another user.' }
      }
      const merged: Record<string, TabState> = {}
      for (const t of desc.tabs) {
        const cur = rec.tabs[t.name] ?? { active: false, values: {} }
        merged[t.name] = { active: cur.active, values: { ...cur.values } }
      }
      for (const [tabName, attrs] of Object.entries(body.changes)) {
        const tab = merged[tabName]
        if (!tab) continue
        for (const [attr, change] of Object.entries(attrs)) {
          const cur = tab.values[attr]
          const several = Array.isArray(cur) || Array.isArray(change.value)
          const wanted = Array.isArray(change.value) ? change.value : emptyLike(change.value) ? [] : [change.value]
          const existing = Array.isArray(cur) ? cur : emptyLike(cur) ? [] : [cur]
          if (change.op === 'clear') tab.values[attr] = several ? [] : null
          else if (change.op === 'set') tab.values[attr] = change.value
          else if (change.op === 'add') {
            const next = [...existing]
            for (const w of wanted) if (!next.some((e) => sameValue(e, w))) next.push(w)
            tab.values[attr] = several ? next : (next[0] ?? null)
          } else {
            const next = existing.filter((e) => !wanted.some((w) => sameValue(e, w)))
            tab.values[attr] = several ? next : (next[0] ?? null)
          }
        }
      }
      const errors = db.validate(desc, merged, rec.dn)
      if (Object.keys(errors).length > 0) {
        return { dn, ok: false, code: 'validation', error: 'Some fields are invalid', fields: errors }
      }
      db.patch(
        rec,
        Object.fromEntries(Object.entries(merged).map(([k, v]) => [k, { active: v.active, values: v.values }])),
      )
      return { dn, ok: true }
    })
    return HttpResponse.json({ results })
  }),

  // ── references ──
  http.get(`${B}/objects/:type/:dn/references`, ({ request, params }) => {
    const denied = session(request, false)
    if (denied) return denied
    const dn = dnParam(params.dn)
    const target = db.get(dn)
    if (!target || target.type !== params.type) return err(404, 'not_found', 'Object not found')
    const wanted = target.dn.toLowerCase()
    const hits: Array<{ dn: string; type: string; label: string; attribute: string }> = []
    for (const type of ['user', 'group', 'role', 'department', 'dns_zone']) {
      const desc = db.descriptor(type)
      for (const rec of db.all(type)) {
        if (rec.dn.toLowerCase() === wanted) continue
        for (const tab of Object.values(rec.tabs)) {
          for (const [attr, v] of Object.entries(tab.values)) {
            const values = Array.isArray(v) ? v : [v]
            if (values.some((x) => typeof x === 'string' && x.toLowerCase() === wanted)) {
              const label = textOf(rec.tabs.main?.values[desc?.name_attr ?? 'cn'])
              hits.push({ dn: rec.dn, type, label: label || rec.dn, attribute: attr })
            }
          }
        }
      }
    }
    hits.sort((a, b) => a.type.localeCompare(b.type) || a.label.localeCompare(b.label))
    return HttpResponse.json(hits)
  }),

  // ── snapshots: store the values, list and restore deleted objects ──
  http.post(`${B}/objects/:type/:dn/snapshots`, async ({ request, params }) => {
    const denied = session(request, true)
    if (denied) return denied
    const rec = db.get(dnParam(params.dn))
    const body = (await request.json()) as { description?: string }
    const snap = {
      id: db.newId(),
      description: body.description ?? '',
      created_at: new Date().toISOString(),
      dn: dnParam(params.dn),
      type: String(params.type),
    }
    db.snapshots.set(snap.id, snap)
    if (rec) db.snapshotTabs.set(snap.id, structuredClone(rec.tabs))
    return HttpResponse.json(
      { id: snap.id, description: snap.description, created_at: snap.created_at, object_dn: snap.dn, type: snap.type, source: 'manual' },
      { status: 201 },
    )
  }),

  http.get(`${B}/snapshots/deleted`, ({ request }) => {
    const denied = session(request, false)
    if (denied) return denied
    const type = new URL(request.url).searchParams.get('type')
    const latest = new Map<string, MockSnapshot>()
    for (const s of db.snapshots.values()) {
      if (db.get(s.dn) || (type && s.type !== type)) continue
      const prev = latest.get(s.dn.toLowerCase())
      if (!prev || prev.created_at < s.created_at) latest.set(s.dn.toLowerCase(), s)
    }
    return HttpResponse.json(
      [...latest.values()].map((s) => ({
        id: s.id,
        object_dn: s.dn,
        type: s.type,
        description: s.description,
        created_at: s.created_at,
        source: 'manual',
      })),
    )
  }),

  http.post(`${B}/snapshots/:id/restore`, ({ request, params }) => {
    const denied = session(request, true)
    if (denied) return denied
    const id = String(params.id)
    const snap = db.snapshots.get(id)
    if (!snap) return err(404, 'not_found', 'Snapshot not found')
    const tabs = db.snapshotTabs.get(id)
    const existing = db.get(snap.dn)
    if (tabs) {
      if (existing) existing.tabs = structuredClone(tabs)
      else {
        const base = snap.dn.replace(/^[^,]*,(ou=[^,]*,)?/, '')
        const desc = db.descriptor(snap.type)
        if (desc) db.create(snap.type, base, structuredClone(tabs))
      }
    }
    return HttpResponse.json({ dn: snap.dn, restored: Object.keys(tabs ?? {}) })
  }),

  // ── raw LDIF (served by the compatibility endpoint of the real API) ──
  http.get(`${B}/objects/:type/:dn/ldif`, ({ request, params }) => {
    const denied = session(request, false)
    if (denied) return denied
    const rec = db.get(dnParam(params.dn))
    if (!rec || rec.type !== params.type) return err(404, 'not_found', 'Object not found')
    const lines = [`dn: ${rec.dn}`]
    for (const tab of Object.values(rec.tabs)) {
      for (const [k, v] of Object.entries(tab.values)) {
        if (k === 'userPassword') continue
        for (const x of Array.isArray(v) ? v : [v]) {
          if (typeof x === 'string' || typeof x === 'number') lines.push(`${k}: ${x}`)
        }
      }
    }
    return new HttpResponse(`${lines.join('\n')}\n`, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } })
  }),

  // ── second factors of a user (administrator view and reset) ──
  http.get(`${B}/users/:dn/second-factors`, ({ request, params }) => {
    const denied = factorAccess(request, false, dnParam(params.dn))
    if (denied) return denied
    const { totp, security_keys, recovery_codes } = factorsOf(dnParam(params.dn))
    return HttpResponse.json({ totp, security_keys, recovery_codes, can_reset: true })
  }),

  http.delete(`${B}/users/:dn/second-factors`, ({ request, params }) => {
    const dn = dnParam(params.dn)
    const denied = factorAccess(request, true, dn)
    if (denied) return denied
    db.secondFactors.delete(dn.toLowerCase())
    return new HttpResponse(null, { status: 204 })
  }),

  http.delete(`${B}/users/:dn/second-factors/webauthn/:id`, ({ request, params }) => {
    const dn = dnParam(params.dn)
    const denied = factorAccess(request, true, dn)
    if (denied) return denied
    const current = factorsOf(dn)
    const keys = current.security_keys.filter((k) => k.id !== params.id)
    if (keys.length === current.security_keys.length) return err(404, 'not_found', 'Security key not found')
    db.secondFactors.set(dn.toLowerCase(), { ...current, security_keys: keys })
    return new HttpResponse(null, { status: 204 })
  }),
]

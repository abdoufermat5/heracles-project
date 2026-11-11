import { http, HttpResponse, type HttpHandler } from 'msw'
import type { AuditEvent } from '@/features/audit/types'
import { BASE_DN, db } from './db'

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

function who(index: number): { dn: string; label: string } {
  const rec = db.all('user')[index]
  if (!rec) return { dn: `uid=admin,ou=people,${BASE_DN}`, label: 'Admin' }
  return { dn: rec.dn, label: String(rec.tabs.main?.values.cn ?? rec.dn) }
}

/** A small deterministic log, relative to now, newest first. */
export function seedAuditEvents(now = Date.now()): AuditEvent[] {
  const admin = who(0)
  const other = who(1)
  const mk = (
    n: number,
    ago: number,
    action: string,
    actor: { dn: string; label: string },
    obj: { dn: string; type: string; label: string },
    extra: Partial<AuditEvent> = {},
  ): AuditEvent => ({
    dn: `cn=${String(1000 - n)}-seed,ou=audit,${BASE_DN}`,
    time: new Date(now - ago).toISOString(),
    action,
    actor,
    object: obj,
    ip: '10.0.0.12',
    attributes: [],
    result: 'success',
    ...extra,
  })
  const userObj = { dn: other.dn, type: 'user', label: other.label }
  return [
    mk(1, 5 * MINUTE, 'login', admin, { dn: admin.dn, type: 'user', label: admin.label }, {
      attributes: ['method: password'],
    }),
    mk(2, 20 * MINUTE, 'login_failed', { dn: '', label: 'jsmith' }, { dn: 'jsmith', type: 'user', label: 'jsmith' }, {
      ip: '203.0.113.9',
      result: 'failure',
      attributes: ['login: jsmith', 'reason: invalid credentials'],
    }),
    mk(3, 2 * HOUR, 'modify', admin, userObj, {
      attributes: ['replace mail: new@example.com', 'add telephoneNumber: +33 1 23 45 67 89', 'delete description: (removed)'],
    }),
    mk(4, 5 * HOUR, 'create', admin, { dn: `cn=staff,ou=groups,${BASE_DN}`, type: 'group', label: 'staff' }, {
      attributes: ['cn: staff', 'description: All staff'],
    }),
    mk(5, 26 * HOUR, 'password', other, userObj, { attributes: ['recovery link: requested'] }),
    mk(6, 3 * DAY, 'acl', admin, { dn: `cn=auditor,ou=aclroles,${BASE_DN}`, type: 'acl_role', label: 'auditor' }, {
      attributes: ['role updated'],
    }),
    mk(7, 9 * DAY, 'delete', admin, { dn: `cn=old,ou=groups,${BASE_DN}`, type: 'group', label: 'old' }),
    mk(8, 40 * DAY, 'login', other, userObj, { attributes: ['method: password'] }),
  ]
}

function matches(e: AuditEvent, p: URLSearchParams): boolean {
  const from = p.get('from')
  const to = p.get('to')
  if (from && new Date(e.time) < new Date(from)) return false
  if (to && new Date(e.time) > new Date(to)) return false
  const actor = p.get('actor')
  if (actor && e.actor.dn.toLowerCase() !== actor.toLowerCase()) return false
  const object = p.get('object')
  if (object && !e.object.dn.toLowerCase().endsWith(object.toLowerCase())) return false
  const actions = p.getAll('action')
  if (actions.length > 0 && !actions.includes(e.action)) return false
  const type = p.get('type')
  if (type && e.object.type !== type) return false
  const result = p.get('result')
  if (result && e.result !== result) return false
  const q = p.get('q')?.toLowerCase()
  if (q) {
    const hay = [e.action, e.actor.label, e.actor.dn, e.object.dn, e.object.label, e.ip, ...e.attributes]
      .join(' ')
      .toLowerCase()
    if (!hay.includes(q)) return false
  }
  return true
}

const csvCell = (v: string) => `"${(/^[=+\-@]/.test(v) ? `'${v}` : v).replace(/"/g, '""')}"`

export const auditHandlers: HttpHandler[] = [
  http.get('/api/v2/audit', ({ request }) => {
    if (!db.me()) {
      return HttpResponse.json(
        { error: { code: 'unauthenticated', message: 'Authentication required' } },
        { status: 401 },
      )
    }
    if (db.session.user === 'employee' || db.session.user === 'viewer') {
      return HttpResponse.json(
        { error: { code: 'forbidden', message: 'You cannot read the audit log' } },
        { status: 403 },
      )
    }
    const p = new URL(request.url).searchParams
    const found = seedAuditEvents().filter((e) => matches(e, p))
    if (p.get('format') === 'csv') {
      const lines = [
        'time,action,result,actor_dn,actor,object_type,object_dn,object,ip,attributes',
        ...found.map((e) =>
          [e.time, e.action, e.result, e.actor.dn, e.actor.label, e.object.type, e.object.dn, e.object.label, e.ip, e.attributes.join('; ')]
            .map(csvCell)
            .join(','),
        ),
      ]
      return new HttpResponse(lines.join('\n'), { headers: { 'Content-Type': 'text/csv; charset=utf-8' } })
    }
    const limit = Number(p.get('limit') ?? 50)
    const offset = Number(p.get('cursor') ?? 0)
    const items = found.slice(offset, offset + limit)
    const next = offset + limit < found.length ? String(offset + limit) : null
    return HttpResponse.json({ items, next_cursor: next })
  }),
]

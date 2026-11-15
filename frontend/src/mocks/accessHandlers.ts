import { http, HttpResponse, type HttpHandler } from 'msw'
import type { AccessRequest, EndDateBody } from '@/features/grants/types'
import { db } from './db'

const unauthenticated = () =>
  HttpResponse.json({ error: { code: 'unauthenticated', message: 'Authentication required' } }, { status: 401 })

/** `/api/v2/access`: grant end dates kept in memory. */
export const accessHandlers: HttpHandler[] = [
  http.get('/api/v2/access/me', () => {
    const me = db.me()
    if (!me) return unauthenticated()
    return HttpResponse.json({ items: db.endDates.filter((g) => g.member.toLowerCase() === me.dn.toLowerCase()) })
  }),
  http.get('/api/v2/access/grants', ({ request }) => {
    if (!db.me()) return unauthenticated()
    const p = new URL(request.url).searchParams
    const holder = p.get('holder')?.toLowerCase()
    const member = p.get('member')?.toLowerCase()
    const items = db.endDates.filter(
      (g) => (!holder || g.holder.toLowerCase() === holder) && (!member || g.member.toLowerCase() === member),
    )
    return HttpResponse.json({ items })
  }),
  http.put('/api/v2/access/grants', async ({ request }) => {
    if (!db.me()) return unauthenticated()
    const body = (await request.json()) as EndDateBody
    const same = (g: { holder: string; kind: string; member: string }) =>
      g.holder.toLowerCase() === body.holder.toLowerCase() &&
      g.kind === body.kind &&
      g.member.toLowerCase() === body.member.toLowerCase()
    db.endDates = db.endDates.filter((g) => !same(g))
    if (!body.until) return HttpResponse.json({ grant: null })
    if (body.until < new Date().toISOString().slice(0, 10)) {
      return HttpResponse.json(
        { error: { code: 'validation', message: 'Invalid date', fields: { until: 'The end date must be in the future' } } },
        { status: 422 },
      )
    }
    const grant = { holder: body.holder, kind: body.kind, member: body.member, until: `${body.until}T23:59:59+00:00` }
    db.endDates.push(grant)
    return HttpResponse.json({ grant })
  }),
  http.get('/api/v2/access/requestable', () => {
    const me = db.me()
    if (!me) return unauthenticated()
    const items = db
      .all('group')
      .filter((g) => {
        const members = (g.tabs.main?.values.member as string[] | undefined) ?? []
        return !members.some((m) => m.toLowerCase() === me.dn.toLowerCase())
      })
      .map((g) => ({ dn: g.dn, kind: 'member', label: String(g.tabs.main?.values.cn ?? g.dn), description: '' }))
    return HttpResponse.json({ items, max_days: 90 })
  }),
  http.get('/api/v2/access/requests', ({ request }) => {
    const me = db.me()
    if (!me) return unauthenticated()
    const view = new URL(request.url).searchParams.get('view') ?? 'mine'
    const mine = (r: AccessRequest) => r.member.toLowerCase() === me.dn.toLowerCase()
    const items =
      view === 'mine'
        ? db.accessRequests.filter(mine)
        : db.session.user === 'admin'
          ? db.accessRequests.filter((r) => r.status === 'pending' && !mine(r)).map((r) => ({ ...r, can_decide: true }))
          : []
    return HttpResponse.json({ items })
  }),
  http.post('/api/v2/access/requests', async ({ request }) => {
    const me = db.me()
    if (!me) return unauthenticated()
    const body = (await request.json()) as { target: string; reason: string; until: string | null }
    const target = db.all('group').find((g) => g.dn === body.target)
    const created: AccessRequest = {
      id: `r${db.accessRequests.length + 1}`,
      requester: me.dn,
      member: me.dn,
      target: { dn: body.target, kind: 'member', label: String(target?.tabs.main?.values.cn ?? body.target) },
      reason: body.reason,
      until: body.until ? `${body.until}T23:59:59+00:00` : null,
      status: 'pending',
      created_at: Date.now() / 1000,
      decided_by: '',
      decided_at: null,
      comment: '',
      error: '',
    }
    db.accessRequests.push(created)
    return HttpResponse.json({ request: created }, { status: 201 })
  }),
  http.post('/api/v2/access/requests/:id/:decision', async ({ params, request }) => {
    const me = db.me()
    if (!me) return unauthenticated()
    const found = db.accessRequests.find((r) => r.id === params.id)
    if (!found) return HttpResponse.json({ error: { code: 'not_found', message: 'Request not found' } }, { status: 404 })
    const decision = String(params.decision)
    const comment = decision === 'cancel' ? '' : (((await request.json()) as { comment?: string }).comment ?? '')
    if (decision === 'reject' && !comment.trim()) {
      return HttpResponse.json(
        { error: { code: 'validation', message: 'Comment required', fields: { comment: 'Say why the request is rejected' } } },
        { status: 422 },
      )
    }
    found.status = decision === 'approve' ? 'approved' : decision === 'reject' ? 'rejected' : 'cancelled'
    found.comment = comment
    found.decided_by = me.dn
    return HttpResponse.json({ request: found })
  }),
  http.get('/api/v2/access/queue', () =>
    HttpResponse.json({ approvals: db.accessRequests.filter((r) => r.status === 'pending').length }),
  ),
]

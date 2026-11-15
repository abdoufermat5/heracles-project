import { http, HttpResponse, type HttpHandler } from 'msw'
import type { EndDateBody } from '@/features/access/types'
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
]

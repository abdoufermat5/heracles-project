import { API_BASE, request } from '@/api/client'
import type { AuditFilters, AuditPageData } from './types'

function params(f: AuditFilters): URLSearchParams {
  const p = new URLSearchParams()
  if (f.from) p.set('from', f.from)
  if (f.to) p.set('to', f.to)
  if (f.actor) p.set('actor', f.actor)
  if (f.object) p.set('object', f.object)
  for (const a of f.action ?? []) p.append('action', a)
  if (f.type) p.set('type', f.type)
  if (f.result) p.set('result', f.result)
  if (f.q) p.set('q', f.q)
  if (f.limit) p.set('limit', String(f.limit))
  return p
}

export const auditApi = {
  list: (filters: AuditFilters, cursor: string | null, signal?: AbortSignal) => {
    const p = params(filters)
    if (cursor) p.set('cursor', cursor)
    const qs = p.toString()
    return request<AuditPageData>(`/audit${qs ? `?${qs}` : ''}`, { signal })
  },
  /** Same-origin link: the session cookie authorises the download. */
  exportUrl: (filters: AuditFilters): string => {
    const p = params({ ...filters, limit: undefined })
    p.set('format', 'csv')
    return `${API_BASE}/audit?${p.toString()}`
  },
}

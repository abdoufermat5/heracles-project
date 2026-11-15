import { API_BASE, ApiError, request } from '@/api/client'
import type { ApiErrorBody } from '@/api/types'
import type { AuditFilters, AuditPageData } from './types'

export type AuditExportFormat = 'csv' | 'json'

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
  exportUrl: (filters: AuditFilters, format: AuditExportFormat): string => {
    const p = params({ ...filters, limit: undefined })
    p.set('format', format)
    return `${API_BASE}/audit/export?${p.toString()}`
  },
  /**
   * Fetch an export (needs a recent sign-in: 403 `reauth_required` otherwise). Errors come back
   * as an `ApiError` instead of an error document saved as the download.
   */
  export: async (filters: AuditFilters, format: AuditExportFormat): Promise<{ blob: Blob; name: string }> => {
    const res = await fetch(auditApi.exportUrl(filters, format), { credentials: 'include' })
    if (!res.ok) {
      let body: ApiErrorBody['error']
      try {
        const json = (await res.json()) as Partial<ApiErrorBody>
        body = json.error ?? { code: 'internal', message: res.statusText }
      } catch {
        body = { code: 'internal', message: res.statusText || `HTTP ${res.status}` }
      }
      throw new ApiError(res.status, body, res.headers.get('X-Request-ID') ?? undefined)
    }
    const disposition = res.headers.get('Content-Disposition') ?? ''
    const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `audit-log.${format}`
    return { blob: await res.blob(), name }
  },
}

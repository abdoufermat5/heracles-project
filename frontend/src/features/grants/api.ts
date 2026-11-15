import { API_BASE, ApiError, request } from '@/api/client'
import type { ApiErrorBody } from '@/api/types'
import type {
  AccessRequest,
  Campaign,
  CampaignBody,
  EndDateBody,
  Grant,
  GrantList,
  Requestable,
  ReviewDecision,
  ReviewItem,
} from './types'

export const accessApi = {
  status: (signal?: AbortSignal) => request<{ enabled: boolean }>('/access/status', { signal }),
  me: (signal?: AbortSignal) => request<GrantList>('/access/me', { signal }),
  grantsOf: (holder: string, signal?: AbortSignal) =>
    request<GrantList>('/access/grants', { query: { holder }, signal }),
  grantsFor: (member: string, signal?: AbortSignal) =>
    request<GrantList>('/access/grants', { query: { member }, signal }),
  setEndDate: (body: EndDateBody) =>
    request<{ grant: Grant | null }>('/access/grants', { method: 'PUT', body }),

  /** What can be requested; for `member` (a person the caller may ask for) instead of the caller. */
  requestable: (member?: string, signal?: AbortSignal) =>
    request<{ items: Requestable[]; max_days: number }>('/access/requestable', { query: { member }, signal }),
  requests: (view: 'mine' | 'to_approve' | 'all', signal?: AbortSignal) =>
    request<{ items: AccessRequest[] }>('/access/requests', { query: { view }, signal }),
  createRequest: (body: { target: string; reason: string; until: string | null; member?: string }) =>
    request<{ request: AccessRequest }>('/access/requests', { method: 'POST', body }),
  approve: (id: string, comment: string) =>
    request<{ request: AccessRequest }>(`/access/requests/${id}/approve`, { method: 'POST', body: { comment } }),
  reject: (id: string, comment: string) =>
    request<{ request: AccessRequest }>(`/access/requests/${id}/reject`, { method: 'POST', body: { comment } }),
  cancel: (id: string) => request<{ request: AccessRequest }>(`/access/requests/${id}/cancel`, { method: 'POST' }),
  queue: (signal?: AbortSignal) => request<{ approvals: number; reviews: number }>('/access/queue', { signal }),

  campaigns: (signal?: AbortSignal) =>
    request<{ items: Campaign[]; can_manage: boolean }>('/access/reviews', { signal }),
  campaign: (id: string, signal?: AbortSignal) =>
    request<{ campaign: Campaign; items: ReviewItem[]; can_manage: boolean }>(`/access/reviews/${id}`, { signal }),
  createCampaign: (body: CampaignBody) =>
    request<{ campaign: Campaign }>('/access/reviews', { method: 'POST', body }),
  decideItem: (campaign: string, item: string, decision: ReviewDecision, comment: string) =>
    request<{ item: ReviewItem }>(`/access/reviews/${campaign}/items/${item}`, {
      method: 'POST',
      body: { decision, comment },
    }),
  closeCampaign: (id: string) =>
    request<{ campaign: Campaign; failed: ReviewItem[] }>(`/access/reviews/${id}/close`, { method: 'POST' }),
  /** The report (step-up: 403 `reauth_required` when the sign-in is old). */
  report: async (id: string, format: 'json' | 'csv'): Promise<{ blob: Blob; name: string }> => {
    const res = await fetch(`${API_BASE}/access/reviews/${id}/report?format=${format}`, { credentials: 'include' })
    if (!res.ok) {
      let body: ApiErrorBody['error']
      try {
        body = ((await res.json()) as Partial<ApiErrorBody>).error ?? { code: 'internal', message: res.statusText }
      } catch {
        body = { code: 'internal', message: res.statusText || `HTTP ${res.status}` }
      }
      throw new ApiError(res.status, body, res.headers.get('X-Request-ID') ?? undefined)
    }
    const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? `access-review.${format}`
    return { blob: await res.blob(), name }
  },
}

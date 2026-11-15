import { request } from '@/api/client'
import type { AccessRequest, EndDateBody, Grant, GrantList, Requestable } from './types'

export const accessApi = {
  status: (signal?: AbortSignal) => request<{ enabled: boolean }>('/access/status', { signal }),
  me: (signal?: AbortSignal) => request<GrantList>('/access/me', { signal }),
  grantsOf: (holder: string, signal?: AbortSignal) =>
    request<GrantList>('/access/grants', { query: { holder }, signal }),
  grantsFor: (member: string, signal?: AbortSignal) =>
    request<GrantList>('/access/grants', { query: { member }, signal }),
  setEndDate: (body: EndDateBody) =>
    request<{ grant: Grant | null }>('/access/grants', { method: 'PUT', body }),

  requestable: (signal?: AbortSignal) =>
    request<{ items: Requestable[]; max_days: number }>('/access/requestable', { signal }),
  requests: (view: 'mine' | 'to_approve' | 'all', signal?: AbortSignal) =>
    request<{ items: AccessRequest[] }>('/access/requests', { query: { view }, signal }),
  createRequest: (body: { target: string; reason: string; until: string | null }) =>
    request<{ request: AccessRequest }>('/access/requests', { method: 'POST', body }),
  approve: (id: string, comment: string) =>
    request<{ request: AccessRequest }>(`/access/requests/${id}/approve`, { method: 'POST', body: { comment } }),
  reject: (id: string, comment: string) =>
    request<{ request: AccessRequest }>(`/access/requests/${id}/reject`, { method: 'POST', body: { comment } }),
  cancel: (id: string) => request<{ request: AccessRequest }>(`/access/requests/${id}/cancel`, { method: 'POST' }),
  queue: (signal?: AbortSignal) => request<{ approvals: number }>('/access/queue', { signal }),
}

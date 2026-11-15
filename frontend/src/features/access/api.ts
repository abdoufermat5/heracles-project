import { request } from '@/api/client'
import type { EndDateBody, Grant, GrantList } from './types'

export const accessApi = {
  me: (signal?: AbortSignal) => request<GrantList>('/access/me', { signal }),
  grantsOf: (holder: string, signal?: AbortSignal) =>
    request<GrantList>('/access/grants', { query: { holder }, signal }),
  grantsFor: (member: string, signal?: AbortSignal) =>
    request<GrantList>('/access/grants', { query: { member }, signal }),
  setEndDate: (body: EndDateBody) =>
    request<{ grant: Grant | null }>('/access/grants', { method: 'PUT', body }),
}

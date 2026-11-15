import { useQuery } from '@tanstack/react-query'
import { isApiError } from '@/api/client'
import { accessApi } from './api'
import type { Grant } from './types'

/** End dates of the signed-in person's own access; `enabled` is false without the access plugin. */
export function useMyEndDates() {
  const q = useQuery({
    queryKey: ['access', 'me'],
    queryFn: ({ signal }) => accessApi.me(signal),
    retry: false,
    staleTime: 60_000,
  })
  const missing = q.isError && isApiError(q.error) && q.error.status === 404
  return { ...q, enabled: q.isSuccess && !missing }
}

/** End dates held on one entry, keyed by lower-cased member DN (memberships of `kind`). */
export function useEndDates(holder: string, kind = 'member') {
  const q = useQuery({
    queryKey: ['access', 'grants', holder],
    queryFn: ({ signal }) => accessApi.grantsOf(holder, signal),
    retry: false,
    enabled: Boolean(holder),
  })
  const byMember = new Map<string, Grant>()
  for (const g of q.data?.items ?? []) if (g.kind === kind) byMember.set(g.member.toLowerCase(), g)
  const available = q.isSuccess
  return { ...q, byMember, available }
}

/** `2027-01-31` for an end date (the day it ends, UTC). */
export function endDay(iso: string): string {
  return iso.slice(0, 10)
}

/** Requests waiting for the caller's decision (empty without the access plugin). */
export function useApprovals() {
  return useQuery({
    queryKey: ['access', 'requests', 'to_approve'],
    queryFn: ({ signal }) => accessApi.requests('to_approve', signal),
    retry: false,
  })
}

export function useMyRequests(enabled = true) {
  return useQuery({
    queryKey: ['access', 'requests', 'mine'],
    queryFn: ({ signal }) => accessApi.requests('mine', signal),
    retry: false,
    enabled,
  })
}

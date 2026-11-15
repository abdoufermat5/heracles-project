import { useQuery } from '@tanstack/react-query'
import { isApiError } from '@/api/client'
import { accessApi } from './api'
import type { Grant } from './types'

/** Whether the access plugin answers (a cheap probe: 404 without it). */
export function useAccessAvailable(): boolean {
  const q = useQuery({
    queryKey: ['access', 'status'],
    queryFn: ({ signal }) => accessApi.status(signal),
    retry: false,
    staleTime: 5 * 60_000,
  })
  return q.isSuccess
}

/** End dates of the grants one person holds, keyed by lower-cased holder DN. */
export function usePersonEndDates(member: string) {
  const available = useAccessAvailable()
  const q = useQuery({
    queryKey: ['access', 'grants', 'member', member],
    queryFn: ({ signal }) => accessApi.grantsFor(member, signal),
    retry: false,
    enabled: available && Boolean(member),
  })
  const byHolder = new Map<string, Grant>()
  for (const g of q.data?.items ?? []) byHolder.set(g.holder.toLowerCase(), g)
  return byHolder
}

/** End dates of the signed-in person's own access; `enabled` is false without the access plugin. */
export function useMyEndDates() {
  const available = useAccessAvailable()
  const q = useQuery({
    queryKey: ['access', 'me'],
    queryFn: ({ signal }) => accessApi.me(signal),
    retry: false,
    staleTime: 60_000,
    enabled: available,
  })
  const missing = q.isError && isApiError(q.error) && q.error.status === 404
  return { ...q, enabled: q.isSuccess && !missing }
}

/** End dates held on one entry, keyed by lower-cased member DN (memberships of `kind`). */
export function useEndDates(holder: string, kind = 'member') {
  const plugin = useAccessAvailable()
  const q = useQuery({
    queryKey: ['access', 'grants', holder],
    queryFn: ({ signal }) => accessApi.grantsOf(holder, signal),
    retry: false,
    enabled: plugin && Boolean(holder),
  })
  const byMember = new Map<string, Grant>()
  for (const g of q.data?.items ?? []) if (g.kind === kind) byMember.set(g.member.toLowerCase(), g)
  return { ...q, byMember, available: q.isSuccess }
}

/** `2027-01-31` for an end date (the day it ends, UTC). */
export function endDay(iso: string): string {
  return iso.slice(0, 10)
}

/** Requests waiting for the caller's decision (empty without the access plugin). */
export function useApprovals() {
  const available = useAccessAvailable()
  return useQuery({
    queryKey: ['access', 'requests', 'to_approve'],
    queryFn: ({ signal }) => accessApi.requests('to_approve', signal),
    retry: false,
    enabled: available,
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

export function useCampaigns(enabled = true) {
  return useQuery({
    queryKey: ['access', 'reviews'],
    queryFn: ({ signal }) => accessApi.campaigns(signal),
    retry: false,
    enabled,
  })
}

export function useCampaign(id: string) {
  return useQuery({
    queryKey: ['access', 'reviews', id],
    queryFn: ({ signal }) => accessApi.campaign(id, signal),
    retry: false,
  })
}

export function useAccessQueue() {
  const available = useAccessAvailable()
  return useQuery({
    queryKey: ['access', 'queue'],
    queryFn: ({ signal }) => accessApi.queue(signal),
    retry: false,
    enabled: available,
  })
}

/** `2027-01-31` from Unix seconds. */
export function secondsDay(seconds: number): string {
  return new Date(seconds * 1000).toISOString().slice(0, 10)
}

/** Locale key of a review outcome (`kept: last member` holds a colon, which i18next splits on). */
export function outcomeKey(outcome: string): string {
  return outcome.replace(/[^a-z]+/g, '_')
}

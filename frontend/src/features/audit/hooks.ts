import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query'
import { useTypes } from '@/api/hooks'
import { auditApi } from './api'
import type { AuditFilters } from './types'

export const AUDIT_TYPE = 'audit_event'

/** The audit plugin is enabled when the type list contains its event type. */
export function useAuditEnabled(): { enabled: boolean; pending: boolean } {
  const { data, isPending } = useTypes()
  return { enabled: data?.some((x) => x.name === AUDIT_TYPE) ?? false, pending: isPending }
}

export function useAuditEvents(filters: AuditFilters, enabled = true) {
  return useInfiniteQuery({
    queryKey: ['audit', filters] as const,
    queryFn: ({ pageParam, signal }) => auditApi.list(filters, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
    enabled,
    retry: false,
  })
}

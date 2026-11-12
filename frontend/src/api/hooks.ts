import {
  keepPreviousData,
  type InfiniteData,
  type QueryClient,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from './endpoints'
import type { CreateObjectRequest, ListParams, ObjectList, PatchObjectRequest } from './types'

export const qk = {
  me: ['me'] as const,
  directories: ['directories'] as const,
  types: ['types'] as const,
  type: (name: string) => ['types', name] as const,
  tree: ['tree'] as const,
  objects: (type: string) => ['objects', type] as const,
  list: (type: string, p: ListParams) => ['objects', type, 'list', p] as const,
  object: (type: string, dn: string) => ['objects', type, 'detail', dn] as const,
  refSearch: (type: string, q: string) => ['objects', type, 'ref', q] as const,
  dashboard: ['dashboard'] as const,
  securityKeys: ['security-keys'] as const,
  sessions: ['sessions'] as const,
  totp: ['totp'] as const,
  snapshots: (type: string, dn: string) => ['snapshots', type, dn] as const,
}

export function useMe() {
  return useQuery({ queryKey: qk.me, queryFn: api.me, retry: false, staleTime: 60_000 })
}

export function useDirectories() {
  return useQuery({ queryKey: qk.directories, queryFn: api.directories })
}

export function useTypes() {
  return useQuery({ queryKey: qk.types, queryFn: api.types, staleTime: 5 * 60_000 })
}

export function useTypeDescriptor(name: string) {
  return useQuery({
    queryKey: qk.type(name),
    queryFn: () => api.type(name),
    staleTime: 5 * 60_000,
  })
}

export function useTree() {
  return useQuery({ queryKey: qk.tree, queryFn: api.tree, staleTime: 60_000 })
}

export function useDashboard() {
  return useQuery({ queryKey: qk.dashboard, queryFn: api.dashboard })
}

export function useObjectList(type: string, params: Omit<ListParams, 'cursor'>) {
  return useInfiniteQuery({
    queryKey: qk.list(type, params),
    queryFn: ({ pageParam, signal }) =>
      api.listObjects(type, { ...params, cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  })
}
export function usePaginatedObjectList(type: string, params: ListParams) {
  return useQuery({
    queryKey: qk.list(type, params),
    queryFn: ({ signal }) => api.listObjects(type, params, signal),
    placeholderData: keepPreviousData,
  })
}


/** Async search used by the object_ref combobox. */
export function useRefSearch(refType: string, q: string, enabled = true) {
  return useQuery({
    queryKey: qk.refSearch(refType, q),
    queryFn: ({ signal }) => api.listObjects(refType, { q, limit: 20, scope: 'sub' }, signal),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

export function useObject(type: string, dn: string | null) {
  return useQuery({
    queryKey: qk.object(type, dn ?? ''),
    queryFn: () => api.getObject(type, dn ?? ''),
    enabled: dn !== null,
  })
}

export function useCreateObject(type: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateObjectRequest) => api.createObject(type, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.objects(type) })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
    },
  })
}

export function usePatchObject(type: string, dn: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PatchObjectRequest) => api.patchObject(type, dn, body),
    onSuccess: (data) => {
      qc.setQueryData(qk.object(type, dn), data)
      void qc.invalidateQueries({ queryKey: [...qk.objects(type), 'list'] })
    },
  })
}

export function useDeleteObjects(type: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (dns: string[]) => {
      const results = await Promise.allSettled(dns.map((dn) => api.deleteObject(type, dn)))
      const failed = results.filter((r) => r.status === 'rejected').length
      return { ok: dns.length - failed, failed }
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: qk.objects(type) })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
    },
  })
}

type Snapshot = [readonly unknown[], unknown][]

/** Set `locked` on the matching rows of every cached list (paged or infinite). */
export function patchLockedInCache(qc: QueryClient, type: string, dns: string[], locked: boolean) {
  const wanted = new Set(dns.map((d) => d.toLowerCase()))
  const patchList = (list: ObjectList): ObjectList => ({
    ...list,
    items: list.items.map((i) => (wanted.has(i.dn.toLowerCase()) ? { ...i, locked } : i)),
  })
  qc.setQueriesData<ObjectList | InfiniteData<ObjectList>>(
    { queryKey: [...qk.objects(type), 'list'] },
    (old) => {
      if (!old) return old
      if ('pages' in old) return { ...old, pages: old.pages.map(patchList) }
      return patchList(old)
    },
  )
}

/**
 * Lock / unlock accounts. The lists show the new state at once; a failure puts the
 * previous state back and tells the user.
 */
export function useAccountLock(type: string) {
  const qc = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: async ({ dns, lock }: { dns: string[]; lock: boolean }) => {
      const fn = lock ? api.lockAccount : api.unlockAccount
      const results = await Promise.allSettled(dns.map((dn) => fn(dn)))
      const failed = results.filter((r) => r.status === 'rejected').length
      return { ok: dns.length - failed, failed }
    },
    onMutate: async ({ dns, lock }) => {
      await qc.cancelQueries({ queryKey: qk.objects(type) })
      const previous: Snapshot = qc.getQueriesData({ queryKey: [...qk.objects(type), 'list'] })
      patchLockedInCache(qc, type, dns, lock)
      return { previous }
    },
    // some rows failed: the caller reports the counts; the lists settle on the server state
    onSuccess: (res, _vars, ctx) => {
      if (res.failed > 0) ctx?.previous.forEach(([key, data]) => qc.setQueryData(key, data))
    },
    onError: (_err, _vars, ctx) => {
      ctx?.previous.forEach(([key, data]) => qc.setQueryData(key, data))
      toast.error(t('shellUI.lock.failed'))
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: qk.objects(type) })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
    },
  })
}

/** Warm the cache on link / row intent (hover, focus). Never throws. */
export function usePrefetch() {
  const qc = useQueryClient()
  return {
    type: (name: string) => {
      if (!name) return
      void qc.prefetchQuery({ queryKey: qk.type(name), queryFn: () => api.type(name), staleTime: 5 * 60_000 })
    },
    object: (type: string, dn: string) => {
      void qc.prefetchQuery({ queryKey: qk.object(type, dn), queryFn: () => api.getObject(type, dn) })
      void qc.prefetchQuery({ queryKey: qk.type(type), queryFn: () => api.type(type), staleTime: 5 * 60_000 })
    },
  }
}

export function useObjectAccountLocked(type: string, dn: string | null) {
  return useQuery({
    queryKey: [...qk.objects(type), 'accountLocked', dn],
    queryFn: async () => {
      if (!dn || type !== 'user') return false
      const rdn = dn.split(',')[0]?.replace(/^[^=]+=/, '') ?? dn
      const list = await api.listObjects(type, { q: rdn, limit: 10 })
      const found = list.items.find((i) => i.dn.toLowerCase() === dn.toLowerCase())
      return found?.locked ?? false
    },
    enabled: !!dn && type === 'user',
    staleTime: 30_000,
  })
}

export function useObjectReferences(type: string, dn: string | null | undefined) {
  return useQuery({
    queryKey: ['objects', type, dn, 'references'],
    queryFn: () => (dn ? api.references(type, dn) : Promise.resolve([])),
    enabled: Boolean(dn),
    staleTime: 60_000,
  })
}

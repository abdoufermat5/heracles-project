import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { qk } from '@/api/hooks'
import { adminApi } from './api'
import type { Assignment, ConfigValue, Hook, PluginInfo, RoleInput, RoleTemplate } from './types'

export const ak = {
  caps: ['admin', 'capabilities'] as const,
  catalog: ['admin', 'catalog'] as const,
  roles: ['admin', 'roles'] as const,
  assignments: (dn: string) => ['admin', 'assignments', dn] as const,
  allAssignments: ['admin', 'assignments'] as const,
  config: ['admin', 'config'] as const,
  hooks: ['admin', 'hooks'] as const,
  checks: ['admin', 'checks'] as const,
  plugins: ['admin', 'plugins'] as const,
  tasks: (kind: string, status: string) => ['admin', 'tasks', kind, status] as const,
  taskRuns: ['admin', 'tasks', 'runs'] as const,
}

export function useCapabilities() {
  return useQuery({ queryKey: ak.caps, queryFn: adminApi.capabilities, staleTime: 60_000 })
}

export function useCatalog() {
  return useQuery({ queryKey: ak.catalog, queryFn: adminApi.catalog, staleTime: 5 * 60_000 })
}

export function useRoles() {
  return useQuery({ queryKey: ak.roles, queryFn: adminApi.roles })
}

export function useRoleMutations() {
  const qc = useQueryClient()
  const done = () => void qc.invalidateQueries({ queryKey: ak.roles })
  return {
    create: useMutation({ mutationFn: (b: RoleInput) => adminApi.createRole(b), onSuccess: done }),
    update: useMutation({
      mutationFn: (v: { dn: string; description: string; templates: RoleTemplate[] }) =>
        adminApi.updateRole(v.dn, { description: v.description, templates: v.templates }),
      onSuccess: done,
    }),
    remove: useMutation({
      mutationFn: (v: { dn: string; force?: boolean }) => adminApi.deleteRole(v.dn, v.force),
      onSuccess: () => {
        done()
        void qc.invalidateQueries({ queryKey: ak.allAssignments })
      },
    }),
  }
}

export function useAssignments(dn: string | null) {
  return useQuery({
    queryKey: ak.assignments(dn ?? ''),
    queryFn: () => adminApi.assignments(dn ?? ''),
    enabled: dn !== null,
  })
}

/** Every entry that carries assignments, in one list. */
export function useAllAssignments() {
  return useQuery({ queryKey: ak.allAssignments, queryFn: adminApi.allAssignments })
}

export function useSaveEntryAssignments() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { dn: string; items: Assignment[] }) => adminApi.putAssignments(v.dn, v.items),
    onSuccess: (data) => {
      qc.setQueryData(ak.assignments(data.dn), data)
      void qc.invalidateQueries({ queryKey: ak.allAssignments })
      void qc.invalidateQueries({ queryKey: ak.roles })
    },
  })
}

export function useSaveAssignments(dn: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (items: Assignment[]) => adminApi.putAssignments(dn, items),
    onSuccess: (data) => {
      qc.setQueryData(ak.assignments(dn), data)
      void qc.invalidateQueries({ queryKey: ak.roles })
    },
  })
}

export function useConfig() {
  return useQuery({ queryKey: ak.config, queryFn: adminApi.config })
}

export function useSaveConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (changes: Record<string, ConfigValue>) => adminApi.putConfig(changes),
    onSuccess: (data) => qc.setQueryData(ak.config, data),
  })
}

export function useHooks() {
  return useQuery({ queryKey: ak.hooks, queryFn: adminApi.hooks })
}

export function useSaveHooks() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { hooks: Hook[]; displayOutput?: boolean }) =>
      adminApi.putHooks(v.hooks, v.displayOutput),
    onSuccess: (data) => qc.setQueryData(ak.hooks, data),
  })
}

export function useChecks() {
  return useQuery({ queryKey: ak.checks, queryFn: adminApi.checks })
}

export function useFix() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; dns: string[]; options?: Record<string, string> }) =>
      adminApi.fix(v.id, v.dns, v.options),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ak.checks }),
  })
}

export function usePlugins() {
  return useQuery({ queryKey: ak.plugins, queryFn: adminApi.plugins })
}

/**
 * Switch a plugin on or off. The card flips at once and rolls back on error; afterwards the
 * plugin list, the capabilities and the type queries are refetched, so the sidebar and the
 * editor tabs follow the new set.
 */
export function useTogglePlugin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { name: string; enabled: boolean }) => adminApi.setPlugin(v.name, v.enabled),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: ak.plugins })
      const previous = qc.getQueryData<PluginInfo[]>(ak.plugins)
      qc.setQueryData<PluginInfo[]>(ak.plugins, (list) =>
        list?.map((p) => (p.name === v.name ? { ...p, enabled: v.enabled } : p)),
      )
      return { previous }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData(ak.plugins, ctx.previous)
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['io', 'access'] })
      void qc.invalidateQueries({ queryKey: ak.plugins })
      void qc.invalidateQueries({ queryKey: ak.caps })
      void qc.invalidateQueries({ queryKey: qk.types })
      void qc.invalidateQueries({ queryKey: qk.tree })
    },
  })
}

export function useTasks(kind: string, status: string) {
  return useQuery({
    queryKey: ak.tasks(kind, status),
    queryFn: () => adminApi.tasks({ kind: kind || undefined, status: status || undefined }),
  })
}

export function useTaskRuns() {
  return useQuery({ queryKey: ak.taskRuns, queryFn: () => adminApi.taskRuns() })
}

export function useTaskActions() {
  const qc = useQueryClient()
  const done = () => void qc.invalidateQueries({ queryKey: ['admin', 'tasks'] })
  return {
    run: useMutation({ mutationFn: (dn: string) => adminApi.runTask(dn), onSuccess: done }),
    retry: useMutation({ mutationFn: (dn: string) => adminApi.retryTask(dn), onSuccess: done }),
  }
}

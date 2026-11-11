import { dnPath, request } from '@/api/client'
import type {
  AclRole,
  Capabilities,
  Catalog,
  CheckRightsRequest,
  ConfigValue,
  ConfigView,
  EntryAssignments,
  Assignment,
  FixOutcome,
  HealthCheck,
  Hook,
  HooksView,
  PluginInfo,
  PluginToggleResult,
  RightsReport,
  RoleInput,
  RoleTemplate,
  TaskRun,
  TaskRunOutcome,
  TasksView,
} from './types'

const A = '/admin'

export const adminApi = {
  capabilities: () => request<Capabilities>(`${A}/capabilities`),

  catalog: () => request<Catalog>(`${A}/acl/catalog`),
  roles: () => request<AclRole[]>(`${A}/acl/roles`),
  createRole: (body: RoleInput) => request<AclRole>(`${A}/acl/roles`, { method: 'POST', body }),
  updateRole: (dn: string, body: { description?: string; templates?: RoleTemplate[] }) =>
    request<AclRole>(`${A}/acl/roles/${dnPath(dn)}`, { method: 'PUT', body }),
  deleteRole: (dn: string, force = false) =>
    request<undefined>(`${A}/acl/roles/${dnPath(dn)}`, {
      method: 'DELETE',
      query: { force: force || undefined },
    }),
  allAssignments: () =>
    request<{ dn: string; assignments: Assignment[] }[]>(`${A}/acl/assignments`),
  assignments: (dn: string) => request<EntryAssignments>(`${A}/acl/assignments/${dnPath(dn)}`),
  putAssignments: (dn: string, assignments: Assignment[]) =>
    request<EntryAssignments>(`${A}/acl/assignments/${dnPath(dn)}`, {
      method: 'PUT',
      body: { assignments },
    }),
  checkRights: (body: CheckRightsRequest) =>
    request<RightsReport>(`${A}/acl/check`, { method: 'POST', body }),

  config: () => request<ConfigView>(`${A}/config`),
  putConfig: (changes: Record<string, ConfigValue>) =>
    request<ConfigView>(`${A}/config`, { method: 'PUT', body: { changes } }),
  hooks: () => request<HooksView>(`${A}/hooks`),
  putHooks: (hooks: Hook[], displayOutput?: boolean) =>
    request<HooksView>(`${A}/hooks`, {
      method: 'PUT',
      body: { hooks, display_output: displayOutput },
    }),

  checks: () => request<HealthCheck[]>(`${A}/checks`),
  fix: (id: string, dns: string[], options: Record<string, string> = {}) =>
    request<FixOutcome>(`${A}/checks/${encodeURIComponent(id)}/fix`, {
      method: 'POST',
      body: { dns, options },
    }),

  plugins: () => request<PluginInfo[]>(`${A}/plugins`),
  setPlugin: (name: string, enabled: boolean) =>
    request<PluginToggleResult>(`${A}/plugins/${encodeURIComponent(name)}`, {
      method: 'PATCH',
      body: { enabled },
    }),
  tasks: (p: { kind?: string; status?: string } = {}) =>
    request<TasksView>(`${A}/tasks`, { query: { ...p } }),
  runTask: (dn: string) =>
    request<TaskRunOutcome>(`${A}/tasks/${dnPath(dn)}/run`, { method: 'POST' }),
  taskRuns: (limit = 30) =>
    request<{ runs: TaskRun[] }>(`${A}/tasks/runs`, { query: { limit } }),
  retryTask: (dn: string) =>
    request<{ dn: string; retried: string[] }>(`${A}/tasks/${dnPath(dn)}/retry`, {
      method: 'POST',
    }),
}

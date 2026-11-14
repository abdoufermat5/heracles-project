/** Types of the administration API (`/api/v2/admin`, see docs/specs/08-admin.md). */

export interface Capabilities {
  is_admin: boolean
  /** Administration console (otherwise the self-service portal). */
  console: boolean
  acl: boolean
  config: boolean
  config_write: boolean
  hooks: boolean
  health: boolean
  plugins: boolean
  tasks: boolean
  /** The import / export plugin is available (its rights endpoint need not be asked). */
  io: boolean
}

// ── ACL ───────────────────────────────────────────────────────────────────

export interface CatalogAttribute {
  name: string
  label: string
}

export interface CatalogObject {
  key: string
  label: string
  type: string
  /** Stable name of the tab, and whether it is the main tab of its type. */
  tab?: string
  main?: boolean
  attributes: CatalogAttribute[]
}

export interface CatalogCategory {
  category: string
  label: string
  wildcard: string
  objects: CatalogObject[]
}

export interface Catalog {
  all: string
  categories: CatalogCategory[]
}

export interface AttributeRights {
  name: string
  rights: string
}

export interface RightsBlock {
  object: string
  rights: string
  attributes: AttributeRights[]
}

export interface RoleTemplate {
  /** Stored text; returned unchanged when the template was not edited. */
  raw?: string
  ignored?: boolean
  reason?: string
  index: number
  blocks: RightsBlock[]
}

export interface AclRole {
  dn: string
  cn: string
  description: string
  templates: RoleTemplate[]
  used_by?: number
}

export interface RoleInput {
  base?: string | null
  cn: string
  description: string
  templates: RoleTemplate[]
}

export type AssignmentScope = 'subtree' | 'base'

export interface AssignmentMember {
  dn: string
  kind: 'user' | 'group' | 'role' | 'everyone' | 'missing'
}

export interface Assignment {
  raw?: string
  ignored?: boolean
  reason?: string
  index: number
  scope?: AssignmentScope
  role?: string
  role_name?: string | null
  role_missing?: boolean
  members?: AssignmentMember[] | string[]
  user_filter?: string | null
  target_filter?: string | null
}

export interface EntryAssignments {
  dn: string
  assignments: Assignment[]
}

export interface RightsReport {
  dn: string
  object: string
  rights: string
  attributes: Record<string, string>
  warnings: string[]
  /** `self_only`: the blocks that only apply to the person's own entry. */
  rules: { origin: string; scope: AssignmentScope; blocks: string[]; self_only?: string[] }[]
  bootstrap_admin: boolean
}

export interface CheckRightsRequest {
  user: string
  dn: string
  object: string
  attributes: string[]
}

// ── Configuration ─────────────────────────────────────────────────────────

export type ConfigKind = 'str' | 'text' | 'int' | 'bool' | 'list' | 'select' | 'path'

export type ConfigValue = string | number | boolean | string[] | null

export interface ConfigField {
  key: string
  section: string
  kind: ConfigKind
  honoured: boolean
  options: string[]
  secret: boolean
  default: ConfigValue
  value: ConfigValue
  source: 'directory' | 'default'
  hidden: boolean
}

export interface ConfigView {
  exists: boolean
  can_write: boolean
  sections: string[]
  fields: ConfigField[]
}

export interface Hook {
  tab: string
  mode: string
  command: string
  enabled: boolean
}

export interface HooksView {
  hooks: Hook[]
  invalid: string[]
  display_output: boolean
  modes: string[]
  tabs: string[]
  can_write: boolean
}

// ── Health ────────────────────────────────────────────────────────────────

export type CheckStatus = 'ok' | 'warning' | 'error'

export interface HealthCheck {
  id: string
  status: CheckStatus
  message: string
  /** Stable id of the message (`<check id>.<outcome>`), when the server sends one. */
  message_key?: string
  /** Values interpolated in the localised message (JSON scalars or lists of strings). */
  message_params?: Record<string, string | number | string[]>
  dns: string[]
  fixable: boolean
  options: string[]
}

export interface FixOutcome {
  result: { id: string; fixed: string[]; failed: Record<string, string>; message: string }
  check: HealthCheck | null
}

// ── Plugins and tasks ─────────────────────────────────────────────────────

export interface PluginInfo {
  name: string
  version: string
  /** Registered: available in the schema and switched on. */
  enabled: boolean
  /** Every required objectClass is defined by the directory schema. */
  available: boolean
  /** Cannot be switched off (serves the console itself). */
  locked?: boolean
  missing_object_classes: string[]
  required_object_classes: string[]
  types: { name: string; label: string; category: string }[]
  tabs: { type: string; name: string; label: string }[]
}

export interface PluginToggleResult {
  restart_required: boolean
  plugin: PluginInfo
}

export interface TaskRow {
  dn: string
  name: string
  kind: string
  kind_label: string
  status: string
  created: string | null
  last_run: string | null
  next_run: string | null
  subtasks: { total: number; done: number; failed: number }
  failed_subtasks: string[]
  can_run: boolean
  /** Latest scheduler run of this kind of task, when the run history is available. */
  last_report?: TaskReport | null
}

export interface TaskReport {
  time: string
  status: 'ok' | 'error' | 'skipped' | string
  summary: string
  /** Counters of the run (`mails_sent`, …); the summary is built from them client-side. */
  counts?: Record<string, number>
  errors: string[]
  /** Why the run was skipped (an English sentence from the server), otherwise null. */
  reason?: string | null
  /** Stable id of `reason` (`no_mailer`), for translation; null or absent when it ran. */
  reason_key?: string | null
}

export interface TaskRun {
  id: number
  directory: string
  runner: string
  kind: string
  started: string
  finished: string
  status: 'ok' | 'error' | 'skipped' | string
  counts: Record<string, number>
  errors: string[]
  summary: string
  /** Why the run was skipped (an English sentence from the server), otherwise null. */
  reason: string | null
  /** Stable id of `reason` (`no_mailer`), for translation; null when it ran. */
  reason_key?: string | null
}

export interface TaskCapabilities {
  syslog_configured: boolean
  scheduler_in_process: boolean
  run_history: boolean
}

export interface TaskRunOutcome {
  dn: string
  queued: boolean
  runs: TaskRun[]
}

export interface TasksView {
  tasks: TaskRow[]
  kinds: { name: string; label: string }[]
  summary: { total: number; active: number; failed_subtasks: number }
  capabilities?: TaskCapabilities
}

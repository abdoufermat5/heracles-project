/**
 * Hand-written types for the API v2 contract (docs/specs/04-api-v2.md).
 * Keep this file in sync with the spec; it is the single source of truth for
 * the frontend.
 */

// ── Errors ────────────────────────────────────────────────────────────────

export type ErrorCode =
  | 'unauthenticated'
  | 'forbidden'
  | 'not_found'
  | 'validation'
  | 'locked'
  | 'conflict'
  | 'ldap_error'
  | 'internal'

export interface LockInfo {
  user: string
  since: string
}

export interface ApiErrorBody {
  error: {
    code: ErrorCode | (string & {})
    message: string
    /** keyed by "<tab>.<attr>" */
    fields?: Record<string, string>
    lock?: LockInfo
  }
}

// ── Auth ──────────────────────────────────────────────────────────────────

export interface CsrfResponse {
  token: string
}

export interface Directory {
  id: string
  label: string
}

export type SecondFactorMethod = 'totp' | 'webauthn' | 'recovery'

export interface LoginRequest {
  directory: string
  username: string
  password: string
}

export interface LoginResponse {
  status: 'ok' | 'second_factor'
  methods?: SecondFactorMethod[]
}

export interface SecondFactorRequest {
  method: SecondFactorMethod
  code: string
}

export interface Me {
  dn: string
  uid: string
  display_name: string
  avatar_url: string | null
  is_admin: boolean
  directory: string
  base: string
}

/**
 * NOT in spec 04 yet: password recovery. Proposed endpoints, see README
 * "API contract gaps".
 */
export interface RecoveryRequest {
  directory: string
  username: string
}
export interface RecoveryConfirm {
  token: string
  password: string
}

// ── Metadata ──────────────────────────────────────────────────────────────

export type Category =
  | 'directory'
  | 'access'
  | 'network'
  | 'systems'
  | 'mail'
  | 'workflow'
  | 'configuration'

export const CATEGORIES: readonly Category[] = [
  'directory',
  'access',
  'network',
  'systems',
  'mail',
  'workflow',
  'configuration',
]

export interface TypeSummary {
  name: string
  label: string
  label_plural: string
  icon: string
  category: Category
  can_create: boolean
}

export type AttributeKind =
  | 'string'
  | 'text'
  | 'int'
  | 'float'
  | 'boolean'
  | 'select'
  | 'multiselect'
  | 'date'
  | 'datetime'
  | 'image'
  | 'file'
  | 'password'
  | 'email'
  | 'phone'
  | 'postal_address'
  | 'url'
  | 'object_ref'
  | 'department'
  | 'hidden'
  | 'display'
  | 'list'
  | 'composite'

export interface SelectOption {
  value: string
  label: string
}

export interface AttributeConstraints {
  pattern?: string
  min?: number
  max?: number
  min_length?: number
  max_length?: number
}

export interface AttributeDescriptor {
  name: string
  label: string
  description?: string
  kind: AttributeKind
  required?: boolean
  multivalued?: boolean
  readonly?: boolean
  default?: unknown
  constraints?: AttributeConstraints
  options?: SelectOption[]
  ref_type?: string
  item?: AttributeDescriptor
  fields?: AttributeDescriptor[]
  image?: { max_width: number; max_height: number }
}

export interface SectionDescriptor {
  name: string
  label: string
  attributes: AttributeDescriptor[]
}

export interface TabDescriptor {
  name: string
  label: string
  optional: boolean
  sections: SectionDescriptor[]
}

export interface ColumnDescriptor {
  key: string
  label: string
}

export interface TypeDescriptor {
  name: string
  label: string
  icon: string
  category: Category
  main_attr: string
  name_attr: string
  columns: ColumnDescriptor[]
  tabs: TabDescriptor[]
}

// ── Tree ──────────────────────────────────────────────────────────────────

export type DepartmentKind = 'ou' | 'o' | 'l' | 'c' | 'dc'

export interface TreeNode {
  dn: string
  label: string
  kind: DepartmentKind
  children: TreeNode[]
}

// ── Objects ───────────────────────────────────────────────────────────────

export type AttrValue = unknown
export type Values = Record<string, AttrValue>

export interface ObjectListItem {
  dn: string
  values: Record<string, unknown>
  locked: boolean
}

export interface ObjectList {
  items: ObjectListItem[]
  next_cursor: string | null
  total: number | null
}

export interface ListParams {
  base?: string
  scope?: 'one' | 'sub'
  q?: string
  limit?: number
  cursor?: string | null
  sort?: string
  order?: 'asc' | 'desc'
}

export interface TabState {
  active: boolean
  values: Values
}

export interface TabAcl {
  /** letters among r w c d m */
  object: string
  /** attribute name -> "r" | "rw" */
  attributes: Record<string, string>
}

export interface ObjectDetail {
  dn: string
  type: string
  tabs: Record<string, TabState>
  acl: Record<string, TabAcl>
}

export interface CreateObjectRequest {
  base: string
  template?: string | null
  tabs: Record<string, TabState>
}

export interface PatchObjectRequest {
  tabs: Record<string, { active: boolean; values: Values }>
}

export interface LockResponse {
  lock: LockInfo
}

export interface Snapshot {
  id: string
  description: string
  created_at: string
}

// ── Dashboard ─────────────────────────────────────────────────────────────

export interface DashboardCard {
  key: string
  label: string
  value: number
  trend: number | null
}

export interface Dashboard {
  cards: DashboardCard[]
  locked_users: number
  expiring_passwords: number
  tasks: { pending: number; failed: number }
}

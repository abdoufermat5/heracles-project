/**
 * Hand-written types for the API v2 contract.
 * Keep this file in sync with the backend routes; it is the single source of truth for
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
  | 'directory_unavailable'
  | 'reauth_required'
  | 'last_second_factor'
  | 'second_factor_required'
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

/** `GET /status`: directory availability and the server build version. */
export interface ServerStatus {
  directories: Record<string, { available: boolean; read_only: boolean }>
  version: string
}

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
  /** TOTP / recovery code. */
  code?: string
  /** Browser assertion (JSON form) for method `webauthn`. */
  credential?: Record<string, unknown>
}

/** WebAuthn options as returned by the API (JSON form of the browser option objects). */
export interface WebAuthnOptionsResponse<T = Record<string, unknown>> {
  options: T
}

export interface WebAuthnCredentialInfo {
  /** base64url credential id */
  id: string
  label: string
  sign_count: number
}

/** One active session of the signed-in person (`GET /auth/sessions`). */
export interface SessionInfo {
  /** Opaque reference (not the cookie value). */
  id: string
  user_agent: string
  ip: string
  /** Unix seconds. */
  created_at: number
  last_seen: number
  current: boolean
}

/** What confirms the identity again before a sensitive change. */
export type ReauthProof = { password: string } | { method: 'totp' | 'recovery'; code: string }

export interface WebAuthnRegisterRequest {
  label: string
  credential: Record<string, unknown>
}

export interface TotpStatus {
  enabled: boolean
  recovery_codes_remaining: number
  security_keys: number
}

/** A TOTP secret awaiting its first valid code. */
export interface TotpEnrolment {
  secret: string
  /** `otpauth://` URI, shown as a QR code. */
  uri: string
  expires_in: number
}

export interface RecoveryCodes {
  codes: string[]
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

/** Password recovery request and confirmation bodies. */
export interface RecoveryRequest {
  email: string
  directory?: string
}
export interface RecoveryConfirm {
  login: string
  token: string
  password: string
  directory?: string
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
  // --- navigation metadata ---
  nav: NavLevel
  nav_group: NavGroup
  count_key: string | null
  // --- end navigation metadata ---
  /** Type capability flags: false for types Heracles writes itself (absent = true). */
  creatable?: boolean
  editable?: boolean
  deletable?: boolean
}

/** How a type appears in the sidebar: a link, under "More", or only in the palette. */
export type NavLevel = 'primary' | 'secondary' | 'hidden'
export type NavGroup =
  | 'people'
  | 'organization'
  | 'access'
  | 'infrastructure'
  | 'mail'
  | 'activity'
  | 'settings'

export const NAV_GROUPS: readonly NavGroup[] = [
  'people',
  'organization',
  'access',
  'infrastructure',
  'mail',
  'activity',
  'settings',
]

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
  description?: string
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
  creatable?: boolean
  editable?: boolean
  deletable?: boolean
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
  groups_count?: number
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
  offset?: number
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

export interface TriggerOutput {
  /** Failed `post*` triggers and other non-blocking problems reported by the directory. */
  warnings?: string[]
  /** Output of successful triggers, when the configuration asks to show it. */
  messages?: string[]
}

export interface ObjectDetail extends TriggerOutput {
  dn: string
  type: string
  tabs: Record<string, TabState>
  acl: Record<string, TabAcl>
}

export interface ObjectReference {
  dn: string
  type: string
  label: string
  attribute: string
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

/** A group the signed-in person belongs to (GET /auth/me/groups). */
export interface MyGroup {
  dn: string
  name: string
  description: string
}

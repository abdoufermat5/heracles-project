/** Contract of `GET /api/v2/audit`. */

export type AuditAction =
  | 'create'
  | 'modify'
  | 'delete'
  | 'login'
  | 'login_failed'
  | 'logout'
  | 'password'
  | 'second_factor'
  | 'acl'
  | 'config'
  | 'import'
  | 'task'

export const AUDIT_ACTIONS: AuditAction[] = [
  'create',
  'modify',
  'delete',
  'login',
  'login_failed',
  'logout',
  'password',
  'second_factor',
  'acl',
  'config',
  'import',
  'task',
]

/** Actions about signing in, as opposed to changes made to the directory. */
export const SIGN_IN_ACTIONS: AuditAction[] = ['login', 'login_failed', 'logout']
export const CHANGE_ACTIONS: AuditAction[] = AUDIT_ACTIONS.filter((a) => !SIGN_IN_ACTIONS.includes(a))

export interface AuditEvent {
  dn: string
  /** ISO 8601, UTC. */
  time: string
  action: AuditAction | (string & {})
  /** `dn` is empty when the author is unknown (failed sign-in); `label` is then the attempted login. */
  actor: { dn: string; label: string }
  object: { dn: string; type: string; label: string }
  ip: string
  /** Changed attributes, e.g. `replace mail: a@example.com` or `uid: jdoe`. */
  attributes: string[]
  result: 'success' | 'failure' | (string & {})
}

export interface AuditPageData {
  items: AuditEvent[]
  next_cursor: string | null
}

export interface AuditFilters {
  from?: string
  to?: string
  actor?: string
  /** DN; matches the object and everything below it. */
  object?: string
  action?: string[]
  type?: string
  result?: string
  q?: string
  limit?: number
}

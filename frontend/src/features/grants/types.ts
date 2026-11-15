/** Contracts of `/api/v2/access`. */

export interface Grant {
  /** DN of the entry holding the grant (group, role, ACL assignment carrier). */
  holder: string
  /** Membership attribute (`member`, `uniqueMember`, `roleOccupant`) or `acl`. */
  kind: string
  member: string
  /** ISO 8601, UTC. */
  until: string
  acl_scope?: string
  acl_role?: string
}

export interface GrantList {
  items: Grant[]
}

export interface EndDateBody {
  holder: string
  kind: string
  member: string
  /** ISO date (ends that day, UTC) or date-time; null makes the grant permanent. */
  until: string | null
  acl_scope?: string
  acl_role?: string
}

export type RequestStatus = 'pending' | 'approved' | 'rejected' | 'cancelled' | 'failed'

export interface AccessRequest {
  id: string
  requester: string
  member: string
  target: { dn: string; kind: string; label: string }
  reason: string
  until: string | null
  status: RequestStatus
  /** Unix seconds. */
  created_at: number
  decided_by: string
  decided_at: number | null
  comment: string
  error: string
  /** Present in the approver views. */
  can_decide?: boolean
}

export interface Requestable {
  dn: string
  kind: string
  label: string
  description: string
  /** Held until this date (ISO): a request extends it. */
  renews: string | null
}

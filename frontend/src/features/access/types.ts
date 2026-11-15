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

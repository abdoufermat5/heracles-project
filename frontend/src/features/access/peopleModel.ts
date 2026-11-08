import type { Assignment, AssignmentMember } from '@/features/admin/types'
import { rdnValue } from '@/lib/objects'

/** The literal member that means "every user". */
export const EVERYONE = '*'

/** Members as objects, whichever shape the API or a draft used. */
export function normaliseMembers(assignment: Assignment): AssignmentMember[] {
  return (assignment.members ?? []).map((member) =>
    typeof member === 'string'
      ? { dn: member, kind: member === EVERYONE ? 'everyone' : 'user' }
      : member,
  )
}

/** What to call one member: its name, or "Every user" for the wildcard. */
export function memberLabel(member: AssignmentMember, everyoneLabel: string): string {
  return member.dn === EVERYONE ? everyoneLabel : rdnValue(member.dn)
}

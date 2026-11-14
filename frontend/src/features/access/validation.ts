/**
 * Rules of the role and assignment forms. The server applies the same ones
 * (`heracles.acl.admin`: `check_role_name`, role description, assignment filters), so a value
 * refused here is refused there and the other way round.
 */
import i18n from 'i18next'
import type { FieldErrors } from '@/lib/liveForm'
import { checkFormat } from '@/lib/formats'

export const ROLE_NAME_MAX = 64
export const ROLE_DESCRIPTION_MAX = 512

// eslint-disable-next-line no-control-regex
const FORBIDDEN_IN_ROLE_NAME = /[,#;:+="<>\\\u0000-\u001f\u007f]/

export interface RoleValues extends Record<string, unknown> {
  cn: string
  description: string
}

/** `taken`: lower-cased names of the roles already in the container the new role goes to. */
export function roleErrors(
  v: RoleValues,
  { creating, taken }: { creating: boolean; taken: ReadonlySet<string> },
): FieldErrors {
  const out: FieldErrors = {}
  const t = (key: string, options?: Record<string, unknown>) => i18n.t(key, options)
  if (creating) {
    const name = v.cn.trim()
    if (name === '') out.cn = t('validation.required')
    else if (name.length > ROLE_NAME_MAX) out.cn = t('validation.maxLength', { count: ROLE_NAME_MAX })
    else if (FORBIDDEN_IN_ROLE_NAME.test(name)) out.cn = t('accessUI.editor.errors.nameChars')
    else if (taken.has(name.toLowerCase())) out.cn = t('accessUI.editor.errors.nameTaken')
  }
  if (v.description.trim().length > ROLE_DESCRIPTION_MAX) {
    out.description = t('validation.maxLength', { count: ROLE_DESCRIPTION_MAX })
  }
  return out
}

export interface AssignmentValues extends Record<string, unknown> {
  role: string
  where: string | null
  members: string[]
  everyone: boolean
  user_filter: string
  target_filter: string
}

export function assignmentErrors(v: AssignmentValues): FieldErrors {
  const out: FieldErrors = {}
  if (v.where === null) out.where = i18n.t('accessUI.people.errors.where')
  if (v.role === '') out.role = i18n.t('accessUI.people.errors.role')
  if (!v.everyone && v.members.length === 0) out.members = i18n.t('accessUI.people.errors.members')
  for (const key of ['user_filter', 'target_filter'] as const) {
    const text = v[key].trim()
    const problem = text === '' ? null : checkFormat('ldap_filter', text)
    if (problem) out[key] = problem
  }
  return out
}

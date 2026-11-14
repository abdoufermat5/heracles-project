import type { TFunction } from 'i18next'
import type { TreeNode } from '@/api/types'
import type { AccountStatus } from '@/components/patterns/StatusBadge'

/**
 * Derives a plain-language account status from directory attributes and lock flag.
 * `password_set` comes with the user listing: an account without any password cannot
 * sign in yet, so it is "pending" rather than "active".
 */
export function getUserStatus(item: {
  locked: boolean
  password_set?: boolean
  values: Record<string, unknown>
}): AccountStatus {
  if (item.locked) return 'locked'
  if (item.password_set === false) return 'pending'

  // Explicit forcePasswordChange requirement
  if (item.values.forcePasswordChange === true) return 'expired'

  // Datetime expiration check
  if (typeof item.values.passwordExpiry === 'string' && item.values.passwordExpiry) {
    const expiry = new Date(item.values.passwordExpiry)
    if (!isNaN(expiry.getTime()) && expiry.getTime() < Date.now()) {
      return 'expired'
    }
  }

  // Employee type pending / disabled states if provided
  const empType = String(item.values.employeeType ?? '').toLowerCase()
  if (empType === 'disabled') return 'disabled'
  if (empType === 'pending') return 'pending'

  return 'active'
}

/**
 * Normalizes text to lowercase alphanumeric without diacritics.
 */
export function normalizeAscii(str: string): string {
  return str
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9._-]/g, '')
}

/**
 * Generates a clean login suggestion: first letter of first name + last name.
 * e.g. "Alice", "Martin" => "amartin"
 */
export function suggestLogin(givenName: string, sn: string): string {
  const g = normalizeAscii(givenName.trim())
  const s = normalizeAscii(sn.trim())
  if (!s) return g
  if (!g) return s
  return `${g[0]}${s}`
}

/**
 * Departments of the tree as a flat list. The tree root is the directory base: it is
 * named by its technical RDN ("heracles"), so it gets the same top-level name as
 * everywhere else ("Racine") instead.
 */
export function flattenDepartments(
  nodes: TreeNode[],
  rootLabel: string,
  isRoot = true,
): Array<{ dn: string; label: string }> {
  const out: Array<{ dn: string; label: string }> = []
  for (const n of nodes) {
    out.push({ dn: n.dn, label: isRoot ? rootLabel : n.label })
    out.push(...flattenDepartments(n.children, rootLabel, false))
  }
  return out
}

/**
 * Saved versions are described by the server in English (the undo point taken before an
 * edit, the safety copy before a restore): known descriptions are shown translated.
 */
export function snapshotDescription(t: TFunction, description: string | null | undefined): string {
  const text = (description ?? '').trim()
  if (text === 'Before edit (undo point)') return t('peopleUI.snapshots.beforeEdit')
  if (text === 'Before restore') return t('peopleUI.snapshots.beforeRestore')
  return text || t('peopleUI.snapshots.untitled')
}

const EMPLOYEE_TYPES = ['employee', 'contractor', 'intern']

/** The wizard's contract types shown by their translated name; other values stay as typed. */
export function employeeTypeLabel(t: TFunction, value: string): string {
  const key = value.trim().toLowerCase()
  return EMPLOYEE_TYPES.includes(key) ? t(`peopleUI.text.${key}`) : value
}

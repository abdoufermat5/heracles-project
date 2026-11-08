import type { AccountStatus } from '@/components/patterns/StatusBadge'

/**
 * Derives a plain-language account status from directory attributes and lock flag.
 */
export function getUserStatus(item: {
  locked: boolean
  values: Record<string, unknown>
}): AccountStatus {
  if (item.locked) return 'locked'

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
 * Generates an email suggestion from login and directory domain.
 */
export function suggestEmail(login: string, domain = 'example.com'): string {
  const cleanLogin = normalizeAscii(login.trim())
  if (!cleanLogin) return ''
  return `${cleanLogin}@${domain}`
}

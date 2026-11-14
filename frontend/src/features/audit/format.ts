import i18n from '@/i18n'
import type { AuditEvent } from './types'

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
]

/** "3 hours ago", in the interface language. */
export function formatRelative(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const rtf = new Intl.RelativeTimeFormat(i18n.language, { numeric: 'auto' })
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit)
  }
  return rtf.format(seconds, 'second')
}

export function formatAbsolute(iso: string): string {
  return new Date(iso).toLocaleString(i18n.language, { dateStyle: 'medium', timeStyle: 'medium' })
}

export type AttributeChange =
  | { kind: 'change'; op: 'add' | 'replace' | 'delete' | 'set'; name: string; value: string }
  | { kind: 'text'; text: string }

const CHANGE_RE = /^(add|replace|delete)\s+([^\s:]+):\s*(.*)$/
const SET_RE = /^([^\s:]+):\s*(.*)$/

/** Parses the attribute lines written by the audit log (`replace mail: a@b`, `uid: jdoe`). */
export function parseAttribute(line: string): AttributeChange {
  const change = CHANGE_RE.exec(line)
  if (change) {
    return {
      kind: 'change',
      op: change[1] as 'add' | 'replace' | 'delete',
      name: change[2] ?? '',
      value: change[3] ?? '',
    }
  }
  const set = SET_RE.exec(line)
  if (set) return { kind: 'change', op: 'set', name: set[1] ?? '', value: set[2] ?? '' }
  return { kind: 'text', text: line }
}

export type Tone = 'success' | 'destructive' | 'secondary' | 'neutral' | 'warning'

export function actionTone(e: Pick<AuditEvent, 'action'>): Tone {
  switch (e.action) {
    case 'delete':
    case 'login_failed':
      return 'destructive'
    case 'create':
    case 'login':
    case 'member_add':
      return 'success'
    case 'logout':
      return 'secondary'
    case 'password':
    case 'second_factor':
    case 'acl':
    case 'lock':
    case 'member_remove':
      return 'warning'
    default:
      return 'neutral'
  }
}

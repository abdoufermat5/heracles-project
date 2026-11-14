/**
 * Named value formats, mirrored from `backend/src/heracles/core/formats.py`: a value the
 * form refuses is refused by the server too. Empty strings pass; required-ness is the
 * caller's decision. Messages are the `validation.format.<name>` translations.
 */
import i18n from 'i18next'

export type Format =
  | 'dn'
  | 'rdn'
  | 'abs_path'
  | 'hostname'
  | 'domain'
  | 'port'
  | 'attribute'
  | 'ldap_filter'
  | 'timezone'
  | 'email'
  | 'http_header'
  | 'id_range'

const ATTR_RE = /^(?:[A-Za-z][A-Za-z0-9-]*|[0-9]+(?:\.[0-9]+)+)$/
const LABEL = '[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
const HOST_RE = new RegExp(`^${LABEL}(?:\\.${LABEL})*$`)
const DOMAIN_RE = new RegExp(`^${LABEL}(?:\\.${LABEL})+$`)
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const HEADER_RE = /^[A-Za-z0-9!#$%&'*+.^_`|~-]+$/
const ID_RANGE_RE = /^([0-9]{1,10})(?:-([0-9]{1,10}))?$/
const MAX_ID = 2 ** 32 - 1

function isIdRange(text: string): boolean {
  const m = ID_RANGE_RE.exec(text)
  if (!m) return false
  const low = Number(m[1])
  if (low > MAX_ID) return false
  return m[2] === undefined || (low < Number(m[2]) && Number(m[2]) <= MAX_ID)
}

/** Split on unescaped commas. */
function splitDn(dn: string): string[] {
  const parts: string[] = []
  let cur = ''
  for (let i = 0; i < dn.length; i++) {
    const ch = dn[i]
    if (ch === '\\' && i + 1 < dn.length) {
      cur += ch + dn[i + 1]
      i++
    } else if (ch === ',') {
      parts.push(cur)
      cur = ''
    } else cur += ch
  }
  parts.push(cur)
  return parts
}

function isRdn(text: string): boolean {
  const eq = text.indexOf('=')
  if (eq < 0) return false
  return ATTR_RE.test(text.slice(0, eq).trim()) && text.slice(eq + 1).trim() !== ''
}

/** Balanced, non-empty parenthesised filter (`(uid=*)`, `(&(a=1)(b=2))`); the server parses fully. */
function isFilter(text: string): boolean {
  const s = text.trim()
  if (!s.startsWith('(') || !s.endsWith(')')) return false
  let depth = 0
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (ch === '\\') {
      i++
      continue
    }
    if (ch === '(') depth++
    else if (ch === ')') {
      depth--
      if (depth < 0 || (depth === 0 && i !== s.length - 1)) return false
    }
  }
  return depth === 0 && /[=~<>]/.test(s)
}

let zones: Set<string> | null = null
function isTimezone(text: string): boolean {
  if (!zones) {
    const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] }
    zones = new Set(intl.supportedValuesOf?.('timeZone') ?? [])
    zones.add('UTC')
  }
  if (zones.size > 1) return zones.has(text)
  try {
    new Intl.DateTimeFormat('en', { timeZone: text })
    return true
  } catch {
    return false
  }
}

const CHECKS: Record<Format, (v: string) => boolean> = {
  dn: (v) => splitDn(v).every(isRdn),
  rdn: (v) => splitDn(v).length === 1 && isRdn(v),
  abs_path: (v) => v.startsWith('/') && !v.includes('\0') && !v.endsWith('/'),
  hostname: (v) => v.length <= 253 && HOST_RE.test(v),
  domain: (v) => v.length <= 253 && DOMAIN_RE.test(v),
  port: (v) => /^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= 65535,
  attribute: (v) => ATTR_RE.test(v),
  ldap_filter: isFilter,
  timezone: isTimezone,
  email: (v) => v.length <= 254 && EMAIL_RE.test(v),
  http_header: (v) => v.length <= 255 && HEADER_RE.test(v),
  id_range: isIdRange,
}

/** Formats added by other modules (mirror of the backend `register`), with their message key. */
const REGISTERED = new Map<string, { matches: (v: string) => boolean; messageKey: string }>()

/** Add a format under `name`; its error is the translation at `messageKey`. */
export function registerFormat(
  name: string,
  matches: (v: string) => boolean,
  messageKey: string,
): void {
  REGISTERED.set(name, { matches, messageKey })
}

/** Whether `value` matches `format` (empty passes). An unknown format accepts everything. */
export function matchesFormat(format: Format | (string & {}), value: string): boolean {
  if (value === '') return true
  const known = CHECKS[format as Format] as ((v: string) => boolean) | undefined
  if (known) return known(value)
  return REGISTERED.get(format)?.matches(value) ?? true
}

/** Translated error for `value`, or `null` when it matches (empty passes). */
export function checkFormat(format: Format | (string & {}), value: string): string | null {
  if (matchesFormat(format, value)) return null
  return i18n.t(REGISTERED.get(format)?.messageKey ?? `validation.format.${format}`)
}

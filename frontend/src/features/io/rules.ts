/**
 * Client-side rules of the import / export forms, mirroring the checks of the
 * `ldapmanager` router: what the form refuses, the server refuses too.
 */
import i18n from 'i18next'
import { checkFormat } from '@/lib/formats'
import type { CsvField } from './api'

const t = (key: string, opts?: Record<string, unknown>): string => i18n.t(key, opts)

export const LDIF_MAX_BYTES = 10 * 1024 * 1024
export const LDIF_MAX_ENTRIES = 5000
export const WRAP_MAX = 1000

// ---------------------------------------------------------------- export

export interface ExportErrors {
  base?: string
  filter?: string
  wrap?: string
}

/** `wrap` is the raw text of the field: nothing is silently clamped. */
export function checkExport(p: { base: string; filter: string; wrap: string }): ExportErrors {
  const errors: ExportErrors = {}
  const base = checkFormat('dn', p.base.trim())
  if (base) errors.base = base
  const filter = checkFormat('ldap_filter', p.filter.trim())
  if (filter) errors.filter = filter
  const wrap = p.wrap.trim()
  if (wrap === '') errors.wrap = t('validation.required')
  else if (!/^-?\d+$/.test(wrap)) errors.wrap = t('validation.integer')
  else if (Number(wrap) < 0) errors.wrap = t('validation.min', { min: 0 })
  else if (Number(wrap) > WRAP_MAX) errors.wrap = t('validation.max', { max: WRAP_MAX })
  return errors
}

// ------------------------------------------------------------------ LDIF

/** First problem of an LDIF document, as an already translated message; `null` when it parses. */
export function checkLdif(text: string): string | null {
  if (new TextEncoder().encode(text).length > LDIF_MAX_BYTES) return t('io.errors.ldif.tooLarge')
  // unfold: a line starting with a space continues the previous one
  const lines: { text: string; no: number }[] = []
  text
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .forEach((raw, i) => {
      const last = lines[lines.length - 1]
      if (raw.startsWith(' ') && last && last.text !== '') last.text += raw.slice(1)
      else lines.push({ text: raw, no: i + 1 })
    })
  let inRecord = false
  let records = 0
  for (const { text: line, no } of lines) {
    if (line.startsWith('#')) continue
    if (line.trim() === '') {
      inRecord = false
      continue
    }
    const colon = line.indexOf(':')
    if (colon <= 0) return t('io.errors.ldif.badLine', { line: no })
    const name = line.slice(0, colon).toLowerCase()
    const rest = line.slice(colon + 1)
    if (rest.startsWith(':')) {
      const b64 = rest.slice(1).trim()
      if (!/^[A-Za-z0-9+/]*={0,2}$/.test(b64) || b64.length % 4 !== 0)
        return t('io.errors.ldif.badBase64', { line: no })
    } else if (rest.startsWith('<')) return t('io.errors.ldif.url', { line: no })
    if (!inRecord) {
      if (name === 'version') continue
      if (name !== 'dn') return t('io.errors.ldif.noDn', { line: no })
      records += 1
      if (records > LDIF_MAX_ENTRIES) return t('io.errors.ldif.tooMany')
      const value = rest.startsWith(':') ? decodeBase64(rest.slice(1).trim()) : rest.replace(/^ /, '')
      if (value === null || value.trim() === '' || checkFormat('dn', value) !== null)
        return t('io.errors.ldif.badDn', { line: no, value: value ?? '' })
      inRecord = true
    } else if (name === 'dn') return t('io.errors.ldif.dnInside', { line: no })
    else if (name === 'changetype') return t('io.errors.ldif.changetype', { line: no })
  }
  return records === 0 && text.trim() !== '' ? t('io.errors.ldif.empty') : null
}

function decodeBase64(b64: string): string | null {
  try {
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    return null
  }
}

// ------------------------------------------------------------------- CSV

export interface FixedRow {
  id: number
  field: string
  value: string
}

export interface FixedErrors {
  field?: string
  value?: string
}

const TRUE_WORDS = new Set(['1', 'true', 'yes', 'on', 'y', 't'])
const FALSE_WORDS = new Set(['0', 'false', 'no', 'off', 'n', 'f', ''])

/** Problems of one fixed value; `earlier` are the rows above it (an attribute may appear once). */
export function checkFixedRow(
  row: FixedRow,
  earlier: readonly FixedRow[],
  fields: readonly CsvField[],
): FixedErrors {
  const errors: FixedErrors = {}
  if (!row.field) errors.field = t('io.errors.csv.chooseField')
  else if (earlier.some((r) => r.field === row.field)) errors.field = t('io.errors.csv.fixedDuplicate')
  const value = row.value.trim()
  if (value === '') errors.value = t('io.errors.csv.enterValue')
  else {
    const kind = fields.find((f) => f.key === row.field)
    if (kind && !kind.multivalued) {
      if (kind.kind === 'int' && !/^[+-]?\d+$/.test(value)) errors.value = t('validation.integer')
      else if (kind.kind === 'float' && !Number.isFinite(Number(value))) errors.value = t('validation.number')
      else if (kind.kind === 'boolean' && !TRUE_WORDS.has(value.toLowerCase()) && !FALSE_WORDS.has(value.toLowerCase()))
        errors.value = t('io.errors.csv.notBoolean')
    }
  }
  return errors
}

export interface MappingProblems {
  /** Field keys mapped from more than one column. */
  duplicates: Set<string>
  /** Required fields that no column and no fixed value fills. */
  missing: CsvField[]
  nothingMapped: boolean
}

/** `mapping` is column index → field key ('' ignores the column). */
export function checkMapping(
  mapping: Record<number, string>,
  fixed: readonly FixedRow[],
  fields: readonly CsvField[],
  templated: boolean,
): MappingProblems {
  const mapped = Object.values(mapping).filter(Boolean)
  const seen = new Set<string>()
  const duplicates = new Set<string>()
  for (const key of mapped) {
    if (seen.has(key)) duplicates.add(key)
    seen.add(key)
  }
  const covered = new Set([...mapped, ...fixed.filter((r) => r.field && r.value.trim() !== '').map((r) => r.field)])
  const touchedTabs = new Set(fields.filter((f) => covered.has(f.key)).map((f) => f.tab))
  // a template may fill required attributes itself, and only the tabs the import creates count
  const missing = templated
    ? []
    : fields.filter(
        (f) =>
          f.required &&
          !f.has_default &&
          !covered.has(f.key) &&
          (!f.tab_optional || touchedTabs.has(f.tab)),
      )
  return { duplicates, missing, nothingMapped: mapped.length === 0 }
}

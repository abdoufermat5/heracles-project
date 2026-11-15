import i18n from 'i18next'
import { checkFormat, matchesFormat } from '@/lib/formats'
import type { ConfigField, ConfigValue } from './types'
import '@/locales/settings.register'

export type ConfigGroupId =
  | 'general'
  | 'security'
  | 'passwords'
  | 'notifications'
  | 'automation'
  | 'advanced'

export interface ConfigGroupMeta {
  id: ConfigGroupId
  labelKey: string
  helpKey: string
}

export const CONFIG_GROUPS: readonly ConfigGroupMeta[] = [
  {
    id: 'general',
    labelKey: 'settingsUI.config.groups.general',
    helpKey: 'settingsUI.config.groups.generalHelp',
  },
  {
    id: 'security',
    labelKey: 'settingsUI.config.groups.security',
    helpKey: 'settingsUI.config.groups.securityHelp',
  },
  {
    id: 'passwords',
    labelKey: 'settingsUI.config.groups.passwords',
    helpKey: 'settingsUI.config.groups.passwordsHelp',
  },
  {
    id: 'notifications',
    labelKey: 'settingsUI.config.groups.notifications',
    helpKey: 'settingsUI.config.groups.notificationsHelp',
  },
  {
    id: 'automation',
    labelKey: 'settingsUI.config.groups.automation',
    helpKey: 'settingsUI.config.groups.automationHelp',
  },
  {
    id: 'advanced',
    labelKey: 'settingsUI.config.groups.advanced',
    helpKey: 'settingsUI.config.groups.advancedHelp',
  },
] as const

/** Value of a field as the form handles it (`null` and `''` are the same "unset" state). */
export function normalise(field: Pick<ConfigField, 'kind'>, value: ConfigValue | undefined): ConfigValue {
  switch (field.kind) {
    case 'bool':
      return value === true
    case 'int':
      return typeof value === 'number' ? value : null
    case 'list':
      return Array.isArray(value) ? value : []
    default:
      return typeof value === 'string' ? value : ''
  }
}

export function sameValue(field: ConfigField, a: ConfigValue | undefined, b: ConfigValue | undefined): boolean {
  return JSON.stringify(normalise(field, a)) === JSON.stringify(normalise(field, b))
}

/** Lines of a multi-value field, as typed in the textarea. */
export function toLines(value: ConfigValue | undefined): string {
  return Array.isArray(value) ? value.join('\n') : ''
}

export function fromLines(text: string): string[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l !== '')
}

/** Legacy section filter: fields shown by the generic form for one legacy section. */
export function sectionFields(fields: ConfigField[], section: string): ConfigField[] {
  if (section === 'triggers') return []
  return fields.filter((f) => f.section === section)
}

/** Determines primary group of a field. */
export function getFieldGroup(field: ConfigField): ConfigGroupId {
  if (field.section === 'password' || field.key.startsWith('password_')) return 'passwords'
  if (
    field.section === 'login' ||
    field.key.startsWith('login_') ||
    field.key.startsWith('cas_') ||
    field.key.startsWith('http_') ||
    field.key === 'session_lifetime'
  ) {
    return 'security'
  }
  if (
    field.section === 'mail_templates' ||
    field.section === 'recovery' ||
    field.key.startsWith('recovery_') ||
    field.key.startsWith('mail_')
  ) {
    return 'notifications'
  }
  if (
    field.section === 'triggers' ||
    field.section === 'tasks' ||
    field.key.startsWith('tasks_') ||
    field.key.startsWith('tab_hooks')
  ) {
    return 'automation'
  }
  if (field.honoured) return 'general'
  return 'advanced'
}

/** Fields belonging to a group. */
export function groupFields(fields: ConfigField[], group: ConfigGroupId): ConfigField[] {
  if (group === 'automation') {
    // Triggers hooks editor has its own dedicated component
    return fields.filter((f) => f.section === 'tasks' || (getFieldGroup(f) === 'automation' && f.section !== 'triggers'))
  }
  if (group === 'advanced') {
    // Advanced group holds all settings flagged "stored for compatibility"
    return fields.filter((f) => !f.honoured)
  }
  // Main groups show relevant honoured/configured settings for that category
  return fields.filter((f) => getFieldGroup(f) === group && (f.honoured || group === 'security' || group === 'notifications'))
}

/** Search fields across all groups by query. */
export function searchFields(
  fields: ConfigField[],
  query: string,
  translate: (key: string) => string,
): ConfigField[] {
  const q = query.trim().toLowerCase()
  if (!q) return fields
  return fields.filter((f) => {
    if (f.section === 'triggers') return false
    const keyMatch = f.key.toLowerCase().includes(q)
    const labelMatch = translate(`config.field.${f.key}`).toLowerCase().includes(q)
    const helpMatch = translate(`settingsUI.config.help.${f.key}`).toLowerCase().includes(q)
    const sectionMatch = translate(`config.section.${f.section}`).toLowerCase().includes(q)
    return keyMatch || labelMatch || helpMatch || sectionMatch
  })
}

/** Draft after changing one field: unchanged values are dropped so only differences are saved. */
export function nextDraft(
  draft: Record<string, ConfigValue>,
  field: ConfigField,
  value: ConfigValue,
): Record<string, ConfigValue> {
  const next = { ...draft }
  if (sameValue(field, value, field.value)) delete next[field.key]
  else next[field.key] = value
  return next
}

// ── validation (mirrors `ConfigField.constraints` and the cross-field rules of the server) ──

const tr = (key: string, opts?: Record<string, unknown>): string => i18n.t(key, opts)

function isUnset(field: Pick<ConfigField, 'kind'>, value: ConfigValue): boolean {
  const v = normalise(field, value)
  if (field.kind === 'bool') return false
  if (field.kind === 'int') return v === null
  if (field.kind === 'list') return (v as string[]).length === 0
  return v === ''
}

/** Value of every setting once `draft` is written; an emptied setting falls back to its default. */
export function effectiveValues(
  fields: ConfigField[],
  draft: Record<string, ConfigValue>,
): Record<string, ConfigValue> {
  const out: Record<string, ConfigValue> = {}
  for (const f of fields) {
    const raw = f.key in draft ? (draft[f.key] ?? null) : f.value
    out[f.key] = normalise(f, f.key in draft && isUnset(f, raw) ? f.default : raw)
  }
  return out
}

function listError(field: ConfigField, items: string[]): string | null {
  const c = field.constraints ?? {}
  const seen = new Set<string>()
  for (const item of items) {
    if (field.options.length > 0 && !field.options.includes(item))
      return tr('config.error.unknownOption', { item })
    if (c.item_format) {
      const message = checkFormat(c.item_format, item)
      if (message) return tr('config.error.item', { item, message })
    }
    if (c.unique && seen.has(item)) return tr('config.error.duplicate', { item })
    seen.add(item)
  }
  return null
}

/** Error of one value on its own (type, bounds, options, format), or `null`. */
function ownError(field: ConfigField, value: ConfigValue): string | null {
  if (field.hidden || isUnset(field, value)) return null
  const c = field.constraints ?? {}
  switch (field.kind) {
    case 'bool':
      return null
    case 'int': {
      if (typeof value !== 'number' || !Number.isInteger(value)) return tr('validation.integer')
      if (c.min !== undefined && value < c.min) return tr('validation.min', { min: c.min })
      if (c.max !== undefined && value > c.max) return tr('validation.max', { max: c.max })
      return null
    }
    case 'list':
      return listError(field, normalise(field, value) as string[])
    case 'select':
      return typeof value === 'string' && field.options.includes(value) ? null : tr('validation.invalid')
    default:
      return c.format && typeof value === 'string' ? checkFormat(c.format, value) : null
  }
}

function intOf(value: ConfigValue | undefined): number | null {
  return typeof value === 'number' && Number.isInteger(value) ? value : null
}

/** Upper bound of an `a-b` identifier range (`null` for a plain base or an invalid value). */
function idRangeEnd(value: ConfigValue | undefined): number | null {
  if (typeof value !== 'string' || value === '' || !matchesFormat('id_range', value)) return null
  const end = value.split('-')[1]
  return end === undefined ? null : Number(end)
}

/**
 * Rules tying several settings together, checked on the values in force after the write. A rule
 * runs only when one of its keys is written; the error goes to the key being written, or to the
 * dependent one (the first of each pair) when both are.
 */
function crossErrors(
  written: ReadonlySet<string>,
  eff: Record<string, ConfigValue>,
): Record<string, string> {
  const errors: Record<string, string> = {}
  const report = (dependent: string, other: string, onDependent: string, onOther: string) => {
    if (!written.has(dependent) && !written.has(other)) return
    if (written.has(dependent) || !written.has(other)) errors[dependent] ??= onDependent
    else errors[other] ??= onOther
  }
  const list = (key: string): string[] => (Array.isArray(eff[key]) ? (eff[key] as string[]) : [])
  const text = (key: string): string => (typeof eff[key] === 'string' ? (eff[key] as string) : '')

  const shells = list('shells')
  const shell = text('default_shell')
  if (shells.length > 0 && shell !== '' && !shells.includes(shell))
    report(
      'default_shell',
      'shells',
      tr('config.error.shellNotListed'),
      tr('config.error.shellsMissingDefault', { value: shell }),
    )
  const allowed = list('password_allowed_hashes')
  const hash = text('password_default_hash')
  if (allowed.length > 0 && hash !== '' && !allowed.includes(hash))
    report(
      'password_default_hash',
      'password_allowed_hashes',
      tr('config.error.hashNotAllowed'),
      tr('config.error.hashesMissingDefault', { value: hash }),
    )
  const length = intOf(eff.password_min_length)
  const differ = intOf(eff.password_min_differ)
  if (length !== null && differ !== null && differ > length)
    report(
      'password_min_differ',
      'password_min_length',
      tr('config.error.differTooLarge', { max: length }),
      tr('config.error.lengthBelowDiffer', { min: differ }),
    )
  for (const kind of ['uid', 'gid']) {
    const low = intOf(eff[`${kind}_pool_min`])
    const high = intOf(eff[`${kind}_pool_max`])
    if (low !== null && high !== null && low > high)
      report(
        `${kind}_pool_max`,
        `${kind}_pool_min`,
        tr('config.error.poolMaxBelowMin', { min: low }),
        tr('config.error.poolMinAboveMax', { max: high }),
      )
  }
  const minId = intOf(eff.min_id)
  for (const kind of ['uid', 'gid'] as const) {
    const end = idRangeEnd(eff[`${kind}_number_base`])
    if (end !== null && minId !== null && end <= minId)
      report(
        `${kind}_number_base`,
        'min_id',
        tr('config.error.rangeEndsBelowMinId', { min: minId }),
        tr(kind === 'uid' ? 'config.error.minIdAboveUidRange' : 'config.error.minIdAboveGidRange', {
          end,
        }),
      )
  }
  return errors
}

/**
 * Error of `value` for `field`, or `null`: its own constraints, then the rules that tie it to
 * other settings (`effective` is `effectiveValues` with this value in place).
 */
export function validateField(
  field: ConfigField,
  value: ConfigValue,
  effective: Record<string, ConfigValue>,
): string | null {
  return (
    ownError(field, value) ??
    crossErrors(new Set([field.key]), { ...effective, [field.key]: normalise(field, value) })[field.key] ??
    null
  )
}

/** Errors of every changed setting, by key: what the server would refuse. */
export function validateDraft(
  fields: ConfigField[],
  draft: Record<string, ConfigValue>,
): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const f of fields) {
    if (!(f.key in draft)) continue
    const message = ownError(f, draft[f.key] ?? null)
    if (message) errors[f.key] = message
  }
  const cross = crossErrors(new Set(Object.keys(draft)), effectiveValues(fields, draft))
  for (const [key, message] of Object.entries(cross)) errors[key] ??= message
  return errors
}

/** The group that owns a setting in the navigation (its first match, so counts are not doubled). */
export function groupOfField(field: ConfigField): ConfigGroupId {
  for (const g of CONFIG_GROUPS) if (groupFields([field], g.id).length > 0) return g.id
  return 'advanced'
}

/** Stored-for-compatibility settings of a list, grouped by legacy section in screen order. */
export function bySection(
  fields: ConfigField[],
  sections: string[],
): { section: string; fields: ConfigField[] }[] {
  return sections
    .map((section) => ({ section, fields: fields.filter((f) => f.section === section) }))
    .filter((s) => s.fields.length > 0)
}

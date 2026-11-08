import type { ConfigField, ConfigValue } from './types'

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

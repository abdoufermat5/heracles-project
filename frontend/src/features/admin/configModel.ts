import type { ConfigField, ConfigValue } from './types'

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

/** Fields shown by the generic form for one section (triggers have their own editor). */
export function sectionFields(fields: ConfigField[], section: string): ConfigField[] {
  if (section === 'triggers') return []
  return fields.filter((f) => f.section === section)
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

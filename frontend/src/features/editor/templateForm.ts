/**
 * Pure helpers of the template screens: the fields-only create form, the values
 * sent to the API and the free-text values of the template editor.
 * See docs/specs/07-objects.md.
 */
import type {
  AttributeDescriptor,
  SectionDescriptor,
  TabDescriptor,
  TypeDescriptor,
  Values,
} from '@/api/types'
import { allAttributes, isEmpty, type FormValues } from '@/lib/objects'
import type { TemplateFields } from './api'

/** Attribute kinds that make no sense in a template (computed, hidden or binary). */
const NOT_TEMPLATABLE = new Set(['display', 'hidden', 'department', 'image', 'file'])

/** Whether the template editor offers an attribute. */
export function isTemplatable(a: AttributeDescriptor): boolean {
  return !NOT_TEMPLATABLE.has(a.kind) && !('stored' in a && a.stored === false)
}

/**
 * The part of a type descriptor a template needs from the user: only the tabs,
 * sections and attributes listed in `fields` (matched case-insensitively), all
 * required. Names no tab declares are asked for as plain text on the first listed tab.
 */
export function fieldsDescriptor(desc: TypeDescriptor, fields: TemplateFields): TypeDescriptor {
  const wanted = new Map<string, Set<string>>()
  for (const [tab, names] of Object.entries(fields)) {
    wanted.set(tab, new Set(names.map((n) => n.toLowerCase())))
  }
  const known = new Set<string>()
  for (const tab of desc.tabs) for (const a of allAttributes(tab)) known.add(`${tab.name}\0${a.name.toLowerCase()}`)

  const tabs: TabDescriptor[] = []
  for (const tab of desc.tabs) {
    const names = wanted.get(tab.name)
    if (!names) continue
    const sections: SectionDescriptor[] = tab.sections
      .map((s) => ({
        ...s,
        attributes: s.attributes
          .filter((a) => names.has(a.name.toLowerCase()) && a.kind !== 'display')
          .map((a) => ({ ...a, required: true, readonly: false })),
      }))
      .filter((s) => s.attributes.length > 0)
    const extra: AttributeDescriptor[] = [...(fields[tab.name] ?? [])]
      .filter((n) => !known.has(`${tab.name}\0${n.toLowerCase()}`))
      .map((n) => ({ name: n, label: n, kind: 'string', required: true }))
    if (extra.length > 0) {
      sections.push({ name: '__extra', label: tab.label, attributes: extra })
    }
    if (sections.length > 0) tabs.push({ ...tab, optional: false, sections })
  }
  return { ...desc, tabs }
}

/** Initial (empty) form values of a fields-only descriptor. */
export function emptyFieldValues(
  fd: TypeDescriptor,
  defaultValue: (a: AttributeDescriptor) => unknown,
): FormValues {
  const out: FormValues = {}
  for (const tab of fd.tabs) {
    const vals: Values = {}
    for (const a of allAttributes(tab)) vals[a.name] = defaultValue(a)
    out[tab.name] = vals
  }
  return out
}

/** `{tab: {attr: value}}` without empty values and password confirmations. */
export function compactValues(values: FormValues): Record<string, Values> {
  const out: Record<string, Values> = {}
  for (const [tab, attrs] of Object.entries(values)) {
    const kept: Values = {}
    for (const [name, v] of Object.entries(attrs ?? {})) {
      if (name.endsWith('__confirm') || (isEmpty(v) && v !== false)) continue
      kept[name] = v
    }
    if (Object.keys(kept).length > 0) out[tab] = kept
  }
  return out
}

/** Create body tabs of "create from template": only what the user filled in. */
export function templateCreateTabs(values: FormValues): Record<string, { active: boolean; values: Values }> {
  return Object.fromEntries(
    Object.entries(compactValues(values)).map(([tab, v]) => [tab, { active: true, values: v }]),
  )
}

// ── Template editor (free text values) ────────────────────────────────────

/** Free text of a template: one string, or a list of strings for multi-valued attributes. */
export type MaskValue = string | string[]
export type MaskValues = Record<string, Record<string, MaskValue>>

/** Whether an attribute holds several values in the template. */
export function isMultiText(a: AttributeDescriptor): boolean {
  return a.kind === 'list' || a.kind === 'multiselect' || a.multivalued === true
}

/** Attributes of a tab the template editor shows. */
export function templateAttributes(tab: TabDescriptor): AttributeDescriptor[] {
  return allAttributes(tab).filter(isTemplatable)
}

/** Editor state from a template detail: one entry per templatable attribute. */
export function maskValuesFromDetail(
  desc: TypeDescriptor,
  tabs: Record<string, { values: Record<string, MaskValue> }> | undefined,
): MaskValues {
  const out: MaskValues = {}
  for (const tab of desc.tabs) {
    const vals: Record<string, MaskValue> = {}
    for (const a of templateAttributes(tab)) {
      const raw = tabs?.[tab.name]?.values[a.name]
      if (isMultiText(a)) vals[a.name] = Array.isArray(raw) ? [...raw] : raw ? [raw] : []
      else vals[a.name] = Array.isArray(raw) ? (raw[0] ?? '') : (raw ?? '')
    }
    out[tab.name] = vals
  }
  return out
}

/**
 * Request tabs for a template. `full` (update) sends every attribute of an active
 * tab, empty ones as `''` so the server removes them; creation only sends what is set.
 */
export function maskRequestTabs(
  desc: TypeDescriptor,
  values: MaskValues,
  active: Record<string, boolean>,
  full: boolean,
): Record<string, { active: boolean; values: Record<string, MaskValue> }> {
  const out: Record<string, { active: boolean; values: Record<string, MaskValue> }> = {}
  for (const tab of desc.tabs) {
    const on = active[tab.name] ?? false
    if (!on) {
      if (full && tab.optional) out[tab.name] = { active: false, values: {} }
      continue
    }
    const vals: Record<string, MaskValue> = {}
    for (const a of templateAttributes(tab)) {
      const v = values[tab.name]?.[a.name]
      if (Array.isArray(v)) {
        const kept = v.filter((x) => x !== '')
        if (kept.length > 0) vals[a.name] = kept
        else if (full) vals[a.name] = []
      } else if (typeof v === 'string' && v !== '') {
        vals[a.name] = v
      } else if (full) {
        vals[a.name] = ''
      }
    }
    out[tab.name] = { active: true, values: vals }
  }
  return out
}

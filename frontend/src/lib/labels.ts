import type { TFunction } from 'i18next'
import type { AttributeDescriptor, TypeDescriptor } from '@/api/types'

/**
 * Object types and attributes arrive from the API with English labels. The chrome
 * translates them by the descriptor's stable id — the type or attribute `name` — and
 * keeps the server string when the catalogue has no entry: plugin types and plugin
 * attributes installed later stay readable untranslated instead of showing a raw key.
 */

/** Singular name of an object type ("Personne", "Groupe"). */
export function typeLabel(t: TFunction, type: { name: string; label: string }): string {
  return t(`labels.types.${type.name}`, { defaultValue: type.label })
}

/** Plural name of an object type, used by headings and navigation entries. */
export function typeLabelPlural(
  t: TFunction,
  type: { name: string; label: string; label_plural?: string },
): string {
  return t(`labels.typePlurals.${type.name}`, { defaultValue: type.label_plural || type.label })
}

// ------------------------------------------------------------ server-provided texts

/**
 * Section, tab, help and option texts have no id that is unique on its own (a section
 * named `identity` exists on four different types with four different labels), so the
 * descriptor carries a stable key for each of them (`label_key`, `description_key`,
 * option `label_key`). The server derives every key from the definitions — type, tab,
 * section, attribute and option value — never from the English wording: renaming a
 * label on the server keeps its translation. A key the catalogue does not know falls
 * back to the wording the server sent.
 */
function translate(t: TFunction, key: string | undefined, fallback: string): string {
  return key ? t(`labels.texts.${key}`, { defaultValue: fallback }) : fallback
}

/**
 * Translation of a label or help text coming from the API, by its stable key.
 * Payloads that are not descriptors (the ACL catalog) pass the wording alone, with no
 * key: it is shown as sent.
 */
export function localText(t: TFunction, key: string, fallback?: string): string {
  return fallback === undefined ? key : translate(t, key, fallback)
}

/**
 * Label of a tab. Plugin tabs are translated by their stable id (`labels.tabs.<name>`);
 * the other tabs by the key of their descriptor.
 */
export function tabLabel(
  t: TFunction,
  tab: { name: string; label: string; label_key?: string },
): string {
  const byName = t(`labels.tabs.${tab.name}`, { defaultValue: '' })
  return byName || translate(t, tab.label_key, tab.label)
}

/**
 * Attribute label: the descriptor's (type-scoped) key first — the same attribute id
 * carries different wording on different types, `l` being "City" on a user and "Name"
 * on a locality — then the id catalogue used by the ACL catalog.
 */
export function attributeLabel(
  t: TFunction,
  name: string,
  fallback: string,
  key?: string,
): string {
  const translated = key ? t(`labels.texts.${key}`, { defaultValue: '' }) : ''
  if (translated) return translated
  return t(`labels.attributes.${name}`, { defaultValue: fallback })
}

/** A type descriptor with every server-provided text translated into the active language. */
export function localizeDescriptor(t: TFunction, d: TypeDescriptor): TypeDescriptor {
  const attr = (a: AttributeDescriptor): AttributeDescriptor => ({
    ...a,
    label: attributeLabel(t, a.name, a.label, a.label_key),
    ...(a.description ? { description: translate(t, a.description_key, a.description) } : {}),
    ...(a.options
      ? { options: a.options.map((o) => ({ ...o, label: translate(t, o.label_key, o.label) })) }
      : {}),
    ...(a.item ? { item: attr(a.item) } : {}),
    ...(a.fields ? { fields: a.fields.map(attr) } : {}),
  })
  return {
    ...d,
    label: typeLabel(t, d),
    columns: d.columns.map((c) => ({
      ...c,
      label: attributeLabel(t, c.key, c.label, c.label_key),
    })),
    tabs: d.tabs.map((tb) => ({
      ...tb,
      // the main tab of a type is named after the type
      label: tb.name === 'main' && tb.label === d.label ? typeLabel(t, d) : tabLabel(t, tb),
      ...(tb.description ? { description: translate(t, tb.description_key, tb.description) } : {}),
      sections: tb.sections.map((s) => ({
        ...s,
        label: translate(t, s.label_key, s.label),
        attributes: s.attributes.map(attr),
      })),
    })),
  }
}

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
 * catalogue `labels.texts` is keyed by the English source text the server sends —
 * `.` and `:` are replaced because i18next reads them as key separators. A text the
 * catalogue does not know keeps the server wording.
 */
function textKey(text: string): string {
  return `labels.texts.${text.replace(/[.:]/g, '_')}`
}

/** Translation of any label or help text coming from the API, by its English wording. */
export function localText(t: TFunction, text: string): string {
  return text ? t(textKey(text), { defaultValue: text }) : text
}

/**
 * Label of a tab. Plugin tabs are translated by their stable id (`labels.tabs.<name>`);
 * the other tabs (`main` on every type, …) by their wording.
 */
export function tabLabel(t: TFunction, tab: { name: string; label: string }): string {
  return t(`labels.tabs.${tab.name}`, { defaultValue: localText(t, tab.label) })
}

/**
 * Attribute label: the same attribute id carries different wording on different types
 * (`l` is "City" on a person and "Name" on a locality), so the server wording is looked
 * up first, then the id catalogue.
 */
export function attributeLabel(t: TFunction, name: string, fallback: string): string {
  return t(textKey(fallback), { defaultValue: t(`labels.attributes.${name}`, { defaultValue: fallback }) })
}

/** A type descriptor with every server-provided text translated into the active language. */
export function localizeDescriptor(t: TFunction, d: TypeDescriptor): TypeDescriptor {
  const attr = (a: AttributeDescriptor): AttributeDescriptor => ({
    ...a,
    label: attributeLabel(t, a.name, a.label),
    ...(a.description ? { description: localText(t, a.description) } : {}),
    ...(a.options
      ? { options: a.options.map((o) => ({ ...o, label: localText(t, o.label) })) }
      : {}),
    ...(a.item ? { item: attr(a.item) } : {}),
    ...(a.fields ? { fields: a.fields.map(attr) } : {}),
  })
  return {
    ...d,
    label: typeLabel(t, d),
    columns: d.columns.map((c) => ({ ...c, label: attributeLabel(t, c.key, c.label) })),
    tabs: d.tabs.map((tb) => ({
      ...tb,
      // the main tab of a type is named after the type
      label: tb.name === 'main' && tb.label === d.label ? typeLabel(t, d) : tabLabel(t, tb),
      ...(tb.description ? { description: localText(t, tb.description) } : {}),
      sections: tb.sections.map((s) => ({
        ...s,
        label: localText(t, s.label),
        attributes: s.attributes.map(attr),
      })),
    })),
  }
}

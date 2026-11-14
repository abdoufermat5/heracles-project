import type { TFunction } from 'i18next'

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

/** Label of an attribute or of a descriptor column (`name` / `key`, and its server label). */
export function attributeLabel(t: TFunction, name: string, fallback: string): string {
  return t(`labels.attributes.${name}`, { defaultValue: fallback })
}

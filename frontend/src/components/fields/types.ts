import type { AttributeDescriptor } from '@/api/types'

export interface FieldInputProps {
  descriptor: AttributeDescriptor
  value: unknown
  onChange: (value: unknown) => void
  /** DOM id of the primary control (label `htmlFor`). */
  id: string
  readOnly?: boolean
  invalid?: boolean
  /** Message for this field. */
  error?: string
  /** Nested errors for list/composite (RHF error tree). */
  errorTree?: unknown
  /** Password confirmation (controlled by the form when provided). */
  confirm?: string
  onConfirmChange?: (value: string) => void
  /** Placeholder of the main input (password fields: "unchanged" by default, for edit forms). */
  placeholder?: string
}

/** Read the message at a sub-path of an RHF error tree. */
export function errorAt(tree: unknown, ...path: (string | number)[]): string | undefined {
  let cur: unknown = tree
  for (const k of path) {
    if (typeof cur !== 'object' || cur === null) return undefined
    cur = (cur as Record<string | number, unknown>)[k]
  }
  if (typeof cur === 'object' && cur !== null && 'message' in cur) {
    const m = (cur as { message?: unknown }).message
    return typeof m === 'string' ? m : undefined
  }
  return undefined
}

export function subTree(tree: unknown, ...path: (string | number)[]): unknown {
  let cur: unknown = tree
  for (const k of path) {
    if (typeof cur !== 'object' || cur === null) return undefined
    cur = (cur as Record<string | number, unknown>)[k]
  }
  return cur
}

/** True when a field should span the full width of the section grid. */
export function isWide(a: AttributeDescriptor): boolean {
  return (
    a.kind === 'text' ||
    a.kind === 'postal_address' ||
    a.kind === 'list' ||
    a.kind === 'composite' ||
    a.kind === 'multiselect' ||
    a.kind === 'image' ||
    a.kind === 'file' ||
    (a.multivalued === true && a.kind !== 'object_ref')
  )
}

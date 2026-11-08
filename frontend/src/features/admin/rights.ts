import type { Assignment } from './types'

/** Rights letters in the order they are displayed. `s` restricts a block to the user's own entry. */
export const RIGHT_LETTERS = ['r', 'w', 'c', 'd', 'm', 't', 's'] as const
export type RightLetter = (typeof RIGHT_LETTERS)[number]

export function hasRight(rights: string, letter: string): boolean {
  return rights.includes(letter)
}

/** Add or remove one right, keeping the canonical order (`s` first). */
export function toggleRight(rights: string, letter: RightLetter): string {
  const set = new Set(rights.split(''))
  if (set.has(letter)) set.delete(letter)
  else set.add(letter)
  const order = ['s', 'r', 'w', 'c', 'd', 'm', 't']
  const known = order.filter((l) => set.has(l))
  const unknown = [...set].filter((l) => !order.includes(l))
  return [...known, ...unknown].join('')
}

/** Short summary such as `rwcdm` or `—` for the table cells. */
export function rightsLabel(rights: string): string {
  return rights === '' ? '—' : rights
}

export function nextIndex(items: { index: number }[]): number {
  return items.reduce((max, i) => Math.max(max, i.index), -1) + 1
}

/** DNs of an assignment's members (the API sends objects, drafts may hold plain strings). */
export function memberDns(a: Assignment): string[] {
  return (a.members ?? []).map((m) => (typeof m === 'string' ? m : m.dn))
}

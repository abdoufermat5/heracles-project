
export type Density = 'comfortable' | 'compact'
export type StatusFilter = 'all' | 'active' | 'locked' | 'expired'

export const DENSITY_STORAGE_KEY = 'heracles.listing.density'
export const COLUMN_VISIBILITY_PREFIX = 'heracles.listing.columns.'

export interface ListingFilterState {
  status: StatusFilter
}

export function formatCellValue(v: unknown, yes: string, no: string): string {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'boolean') return v ? yes : no
  return String(v)
}

export function isMonospaceKey(key: string): boolean {
  const k = key.toLowerCase()
  return (
    k === 'uid' ||
    k === 'dn' ||
    k === 'entryuuid' ||
    k === 'zonename' ||
    k === 'macaddress' ||
    k === 'iphostnumber' ||
    k === 'gidnumber' ||
    k === 'uidnumber'
  )
}

export function loadColumnVisibility(type: string): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(`${COLUMN_VISIBILITY_PREFIX}${type}`)
    if (raw) return JSON.parse(raw) as Record<string, boolean>
  } catch {
    /* ignore corrupted localStorage */
  }
  return {}
}

export function saveColumnVisibility(type: string, visibility: Record<string, boolean>): void {
  try {
    localStorage.setItem(`${COLUMN_VISIBILITY_PREFIX}${type}`, JSON.stringify(visibility))
  } catch {
    /* ignore storage quota errors */
  }
}

export function loadDensity(): Density {
  try {
    const raw = localStorage.getItem(DENSITY_STORAGE_KEY)
    if (raw === 'compact' || raw === 'comfortable') return raw
  } catch {
    /* ignore */
  }
  // Console users are technical staff: dense rows unless they chose otherwise.
  return 'compact'
}

export function saveDensity(density: Density): void {
  try {
    localStorage.setItem(DENSITY_STORAGE_KEY, density)
  } catch {
    /* ignore */
  }
}

export const COLUMN_ORDER_PREFIX = 'heracles.listing.colorder.'
export const COLUMN_SIZING_PREFIX = 'heracles.listing.colwidths.'

export function loadColumnOrder(type: string): string[] {
  try {
    const raw = localStorage.getItem(`${COLUMN_ORDER_PREFIX}${type}`)
    if (raw) {
      const v: unknown = JSON.parse(raw)
      if (Array.isArray(v)) return v.filter((x): x is string => typeof x === 'string')
    }
  } catch {
    /* ignore */
  }
  return []
}

export function saveColumnOrder(type: string, order: string[]): void {
  try {
    localStorage.setItem(`${COLUMN_ORDER_PREFIX}${type}`, JSON.stringify(order))
  } catch {
    /* ignore */
  }
}

export function loadColumnSizing(type: string): Record<string, number> {
  try {
    const raw = localStorage.getItem(`${COLUMN_SIZING_PREFIX}${type}`)
    if (raw) return JSON.parse(raw) as Record<string, number>
  } catch {
    /* ignore */
  }
  return {}
}

export function saveColumnSizing(type: string, sizing: Record<string, number>): void {
  try {
    localStorage.setItem(`${COLUMN_SIZING_PREFIX}${type}`, JSON.stringify(sizing))
  } catch {
    /* ignore */
  }
}

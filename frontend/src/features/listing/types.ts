
export type Density = 'comfortable' | 'compact'
export type StatusFilter = 'all' | 'active' | 'locked'

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

export function getInitials(name?: string | null): string {
  if (!name) return '?'
  const clean = name.trim()
  if (!clean) return '?'
  const parts = clean.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    const first = parts[0]?.[0] ?? ''
    const last = parts[parts.length - 1]?.[0] ?? ''
    return (first + last).toUpperCase()
  }
  return clean.slice(0, 2).toUpperCase()
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
  return 'comfortable'
}

export function saveDensity(density: Density): void {
  try {
    localStorage.setItem(DENSITY_STORAGE_KEY, density)
  } catch {
    /* ignore */
  }
}

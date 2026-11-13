export interface RecentItem {
  dn: string
  type: string
  title: string
  subtitle?: string
  visitedAt: number
}

export const RECENT_KEY = 'heracles.recent.objects'

export function getRecentItems(): RecentItem[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function addRecentItem(item: Omit<RecentItem, 'visitedAt'>) {
  try {
    const current = getRecentItems().filter((x) => x.dn.toLowerCase() !== item.dn.toLowerCase())
    const next = [{ ...item, visitedAt: Date.now() }, ...current].slice(0, 8)
    localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch {
    /* ignore */
  }
}

/** Forget the visited objects: they belong to the person who signed out (shared browsers). */
export function clearRecentItems() {
  try {
    localStorage.removeItem(RECENT_KEY)
  } catch {
    /* ignore */
  }
}

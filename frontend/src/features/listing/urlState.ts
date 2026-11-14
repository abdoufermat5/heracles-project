import { useNavigate, useSearch } from '@tanstack/react-router'
import { useCallback } from 'react'

/** Page sizes the listing offers. */
export const PAGE_SIZES = [25, 50, 100, 250, 500]
export const DEFAULT_PAGE_SIZE = 25

export type ListStatus = 'active' | 'locked' | 'expired'

/**
 * Status behind a view named by a link (`?filter=locked`, dashboard cards). The view is the
 * status filter: choosing a view in the toolbar writes `status` to the URL, nothing else
 * remembers it.
 */
export function statusOfView(view: string | undefined): ListStatus | undefined {
  if (view === 'active' || view === 'locked') return view
  return view === 'expiring' ? 'expired' : undefined
}

/**
 * Everything that defines a listing view, kept in the URL so a view can be shared,
 * bookmarked and walked with back/forward. Absent keys mean "default".
 */
export interface ListSearch {
  view?: 'templates'
  /** Saved view (dashboard links). */
  filter?: 'active' | 'locked' | 'expiring'
  q?: string
  status?: ListStatus
  base?: string
  scope?: 'one' | 'sub'
  sort?: string
  desc?: boolean
  page?: number
  size?: number
  /** Raw LDAP filter. */
  ldap?: string
  /** Hidden column keys. */
  hide?: string[]
}

function str(v: unknown): string | undefined {
  if (typeof v === 'number') return String(v)
  return typeof v === 'string' && v !== '' ? v : undefined
}

function posInt(v: unknown): number | undefined {
  const n = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN
  return Number.isInteger(n) && n > 0 ? n : undefined
}

/** Router `validateSearch` of the listing route: anything malformed is dropped. */
export function parseListSearch(s: Record<string, unknown>): ListSearch {
  const size = posInt(s.size)
  const hide = Array.isArray(s.hide)
    ? s.hide.filter((x): x is string => typeof x === 'string' && x !== '')
    : undefined
  return {
    view: s.view === 'templates' ? 'templates' : undefined,
    filter:
      s.filter === 'active' || s.filter === 'locked' || s.filter === 'expiring'
        ? s.filter
        : undefined,
    q: str(s.q),
    status:
      s.status === 'active' || s.status === 'locked' || s.status === 'expired'
        ? s.status
        : undefined,
    base: str(s.base),
    scope: s.scope === 'one' || s.scope === 'sub' ? s.scope : undefined,
    sort: str(s.sort),
    desc: s.desc === true || s.desc === 'true' ? true : undefined,
    page: posInt(s.page),
    size: size && PAGE_SIZES.includes(size) ? size : undefined,
    ldap: str(s.ldap),
    hide: hide && hide.length > 0 ? hide : undefined,
  }
}

/** Drops empty values so the URL stays short. */
export function cleanListSearch(s: ListSearch): ListSearch {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === '' || v === false) continue
    if (Array.isArray(v) && v.length === 0) continue
    if (k === 'page' && v === 1) continue
    out[k] = v
  }
  return out as ListSearch
}

/** Reads the listing view from the URL and updates it (history entry unless `replace`). */
export function useListSearch() {
  const navigate = useNavigate()
  const search = useSearch({ strict: false }) as ListSearch
  const update = useCallback(
    (patch: Partial<ListSearch>, replace = false) => {
      void navigate({
        to: '.',
        search: ((prev: ListSearch) => cleanListSearch({ ...prev, ...patch })) as never,
        replace,
      })
    },
    [navigate],
  )
  return { search, update }
}

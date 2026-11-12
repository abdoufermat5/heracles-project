import {
  Copy,
  FilePlus2,
  HeartPulse,
  History,
  Languages,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Moon,
  ShieldCheck,
  SlidersHorizontal,
  User,
  UserPlus,
  Users,
  type LucideIcon,
} from 'lucide-react'
import type { TFunction } from 'i18next'
import type { Capabilities } from '@/features/admin/types'

/** `g x` navigation shortcuts, shared by the keyboard layer and the palette. */
export interface NavShortcut {
  combo: string
  to: string
  params?: Record<string, string>
  labelKey: string
  icon: LucideIcon
  /** Needs this capability (absent: always offered). */
  cap?: keyof Capabilities
}

export function navShortcuts(caps: Capabilities | undefined): NavShortcut[] {
  return [
    { combo: 'g d', to: '/', labelKey: 'shellUI.shortcuts.goDashboard', icon: LayoutDashboard },
    { combo: 'g u', to: '/types/$type', params: { type: 'user' }, labelKey: 'shellUI.shortcuts.goUsers', icon: User },
    { combo: 'g g', to: '/types/$type', params: { type: 'group' }, labelKey: 'shellUI.shortcuts.goGroups', icon: Users },
    caps?.acl === false
      ? { combo: 'g r', to: '/types/$type', params: { type: 'role' }, labelKey: 'shellUI.shortcuts.goRoles', icon: ShieldCheck }
      : { combo: 'g r', to: '/admin/access', labelKey: 'shellUI.shortcuts.goRoles', icon: ShieldCheck, cap: 'acl' },
    { combo: 'g a', to: '/activity/audit', labelKey: 'shellUI.shortcuts.goAudit', icon: History },
    { combo: 'g s', to: '/admin/config', labelKey: 'shellUI.shortcuts.goConfig', icon: SlidersHorizontal, cap: 'config' },
    { combo: 'g h', to: '/admin/health', labelKey: 'shellUI.shortcuts.goHealth', icon: HeartPulse, cap: 'health' },
    { combo: 'g t', to: '/admin/tasks', labelKey: 'shellUI.shortcuts.goTasks', icon: ListChecks, cap: 'tasks' },
  ]
}

export interface CurrentObject {
  type: string
  dn: string
}

/** The object whose page is open, from a `/types/<type>/<dn>` pathname. */
export function currentObjectOf(pathname: string): CurrentObject | null {
  const m = /^\/types\/([^/]+)\/([^/]+)$/.exec(pathname)
  if (!m || m[2] === 'new' || m[2] === 'templates') return null
  try {
    return { type: decodeURIComponent(m[1] ?? ''), dn: decodeURIComponent(m[2] ?? '') }
  } catch {
    return null
  }
}

export interface PaletteAction {
  id: string
  label: string
  icon: LucideIcon
  /** Combo (as given to `useHotkey`) shown on the right. */
  shortcut?: string
  destructive?: boolean
  run: () => void
}

export interface ActionContext {
  t: TFunction
  can: { createUser: boolean; createGroup: boolean; acl: boolean }
  current: CurrentObject | null
  /** Readable label of the current object (falls back to its DN). */
  currentLabel?: string
  go: (to: string, opts?: { params?: Record<string, string>; search?: Record<string, string> }) => void
  toggleTheme: () => void
  switchLanguage: () => void
  signOut: () => void
  copyDn: (dn: string) => void
}

/** Non-navigation actions of the palette, in display order. */
export function buildPaletteActions(c: ActionContext): PaletteAction[] {
  const { t, go } = c
  const out: PaletteAction[] = []
  if (c.can.createUser) {
    out.push({
      id: 'new-user',
      label: t('shellUI.palette.newUser'),
      icon: UserPlus,
      run: () => go('/types/$type/new', { params: { type: 'user' } }),
    })
  }
  if (c.can.createGroup) {
    out.push({
      id: 'new-group',
      label: t('shellUI.palette.newGroup'),
      icon: FilePlus2,
      run: () => go('/types/$type/new', { params: { type: 'group' } }),
    })
  }
  if (c.can.acl) {
    out.push({
      id: 'check-rights',
      label: t('shellUI.palette.checkRights'),
      icon: ShieldCheck,
      run: () => go('/admin/access'),
    })
  }
  if (c.current) {
    const { dn } = c.current
    out.push(
      {
        id: 'audit-object',
        label: t('shellUI.palette.auditFor', { label: c.currentLabel ?? dn }),
        icon: History,
        run: () => go('/activity/audit', { search: { object: dn } }),
      },
      {
        id: 'copy-dn',
        label: t('shellUI.palette.copyDn'),
        icon: Copy,
        run: () => c.copyDn(dn),
      },
    )
  }
  out.push(
    { id: 'theme', label: t('shellUI.palette.switchTheme'), icon: Moon, run: c.toggleTheme },
    { id: 'language', label: t('shellUI.palette.switchLanguage'), icon: Languages, run: c.switchLanguage },
    { id: 'sign-out', label: t('shellUI.palette.signOut'), icon: LogOut, destructive: true, run: c.signOut },
  )
  return out
}

/**
 * Fuzzy score of `needle` in `hay`: null when the letters do not appear in order,
 * higher is better (prefix and word-start matches, consecutive letters).
 */
export function fuzzyScore(needle: string, hay: string): number | null {
  const n = needle.trim().toLowerCase()
  if (!n) return 0
  const h = hay.toLowerCase()
  let score = 0
  let from = 0
  let prev = -2
  for (const ch of n) {
    const i = h.indexOf(ch, from)
    if (i < 0) return null
    if (i === prev + 1) score += 3
    if (i === 0 || /[\s,=._-]/.test(h[i - 1] ?? '')) score += 2
    score += 1
    prev = i
    from = i + 1
  }
  if (h.includes(n)) score += 10
  return score - h.length / 100
}

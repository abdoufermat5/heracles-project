import { Link, useRouterState } from '@tanstack/react-router'
import {
  ArrowLeftRight,
  ChevronDown,
  ChevronRight,
  HeartPulse,
  History,
  LayoutDashboard,
  ListChecks,
  Puzzle,
  RotateCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Star,
  type LucideIcon,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { usePrefetch, useTypes } from '@/api/hooks'
import { NAV_GROUPS, type NavGroup, type TypeSummary } from '@/api/types'
import { useCapabilities } from '@/features/admin/hooks'
import { useIoAccess } from '@/features/io/hooks'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { TypeIcon } from '@/lib/icons'
import { typeLabelPlural } from '@/lib/labels'
import { cn } from '@/lib/utils'

const linkBaseClass =
  'group relative flex h-8 min-w-0 flex-1 items-center gap-2.5 rounded-md px-3 text-body font-medium text-sidebar-foreground transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-sidebar hover:bg-sidebar-accent hover:text-sidebar-accent-foreground [&_svg]:opacity-80'
const activeClass =
  'bg-sidebar-accent text-sidebar-accent-foreground! font-medium before:absolute before:top-1.5 before:bottom-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-sidebar-signal'
const disclosureClass =
  'flex h-8 w-full items-center gap-2.5 rounded-md px-3 text-caption font-medium text-sidebar-muted outline-none hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring'

/** Static destinations; `/activity/audit` is a route owned by the audit feature. */
type NavPath =
  | '/'
  | '/types/$type'
  | '/io'
  | '/activity/audit'
  | '/admin/access'
  | '/admin/config'
  | '/admin/health'
  | '/admin/plugins'
  | '/admin/tasks'

// ---------------------------------------------------------------- persistence

/** Retired: directory groups are no longer collapsible; the stale value is dropped. */
const LEGACY_COLLAPSED_KEY = 'heracles.nav.collapsedGroups'
const FAVORITES_KEY = 'heracles.nav.favorites'
const ADMIN_OPEN_KEY = 'heracles.nav.adminOpen'
/** Show the filter input once more links than this are visible. */
const FILTER_THRESHOLD = 15
/** A group with this many types or fewer lists them all. */
const GROUP_FULL_LIMIT = 4

function readList(key: string): string[] {
  try {
    const raw = localStorage.getItem(key)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

function writeList(key: string, value: string[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* storage unavailable: the state just is not remembered */
  }
}

function usePersistedSet(key: string): [Set<string>, (id: string) => void] {
  const [items, setItems] = useState<Set<string>>(() => new Set(readList(key)))
  const toggle = useCallback(
    (id: string) => {
      setItems((prev) => {
        const next = new Set(prev)
        if (!next.delete(id)) next.add(id)
        writeList(key, [...next])
        return next
      })
    },
    [key],
  )
  return [items, toggle]
}

function useAdminOpen(): [boolean, () => void] {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(ADMIN_OPEN_KEY) === '1'
    } catch {
      return false
    }
  })
  const toggle = useCallback(() => {
    setOpen((prev) => {
      try {
        localStorage.setItem(ADMIN_OPEN_KEY, prev ? '0' : '1')
      } catch {
        /* not remembered */
      }
      return !prev
    })
  }, [])
  return [open, toggle]
}

// ------------------------------------------------------------------- the model

/**
 * Types the sidebar does not list: access roles are edited from the access control page,
 * the canonical UI for them.
 */
const HIDDEN_TYPES: ReadonlySet<string> = new Set(['acl_role'])

/**
 * Types shown in another group than the one they declare, as primary entries: the
 * applications people are granted access to belong with access, not with the settings.
 */
const REGROUPED: Readonly<Record<string, NavGroup>> = {
  application: 'access',
  web_application: 'access',
}

const groupOf = (ty: TypeSummary): NavGroup => REGROUPED[ty.name] ?? ty.nav_group
const levelOf = (ty: TypeSummary) => (ty.name in REGROUPED ? 'primary' : ty.nav)

interface NavItem {
  key: string
  to: NavPath
  params?: { type: string }
  label: string
  icon: ReactNode
  /** Object type behind the link: those can be pinned. */
  type?: string
  exact?: boolean
}

function NavLink({
  item,
  collapsed,
  pinned,
  onTogglePin,
}: {
  item: NavItem
  collapsed: boolean
  pinned?: boolean
  onTogglePin?: (type: string) => void
}) {
  const { t } = useTranslation()
  const prefetch = usePrefetch()
  const { label } = item
  const warm = item.type ? () => prefetch.type(item.type ?? '') : undefined
  const link = (
    <Link
      onMouseEnter={warm}
      onFocus={warm}
      to={item.to as never}
      params={item.params as never}
      activeOptions={{ exact: item.exact }}
      className={cn(linkBaseClass, collapsed && 'mx-auto size-8 flex-none justify-center px-0')}
      activeProps={{ className: activeClass, 'aria-current': 'page' }}
      aria-label={collapsed ? label : undefined}
      // The label truncates in the narrow rail; the full text stays readable on hover.
      title={collapsed ? undefined : label}
    >
      {item.icon}
      {!collapsed && <span className="flex-1 truncate">{label}</span>}
    </Link>
  )

  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>{link}</TooltipTrigger>
        <TooltipContent side="right" sideOffset={8} className="flex items-center gap-1.5">
          <span>{label}</span>
        </TooltipContent>
      </Tooltip>
    )
  }

  if (!item.type || !onTogglePin) return link
  const type = item.type
  return (
    <div className="group/row relative flex items-center">
      {link}
      <button
        type="button"
        onClick={() => onTogglePin(type)}
        aria-label={t(pinned ? 'sidebar.unpin' : 'sidebar.pin', { label })}
        aria-pressed={!!pinned}
        className={cn(
          'absolute top-1/2 right-1 -translate-y-1/2 rounded-sm bg-sidebar p-1 outline-none hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring',
          pinned
            ? 'text-sidebar-signal opacity-100'
            : 'text-sidebar-muted opacity-0 group-focus-within/row:opacity-100 group-hover/row:opacity-100',
        )}
      >
        <Star className={cn('size-3.5', pinned && 'fill-current')} aria-hidden />
      </button>
    </div>
  )
}

/** A titled block of links; in the icon-only rail the title becomes a separator. */
function NavSection({
  title,
  collapsed,
  testId,
  level = 'group',
  children,
}: {
  title: string
  collapsed: boolean
  testId: string
  /** `section` is a top-level block heading, `group` a sub-heading inside one. */
  level?: 'section' | 'group'
  children: ReactNode
}) {
  return (
    <div className="space-y-0.5" data-testid={testId}>
      {collapsed ? (
        <div className="mx-1.5 my-1.5 h-px bg-sidebar-border" role="separator" />
      ) : level === 'section' ? (
        <h2 className="label-caps px-3 pt-3 pb-1 text-sidebar-muted select-none">{title}</h2>
      ) : (
        <h3 className="px-3 pt-2 pb-0.5 text-caption font-medium text-sidebar-muted select-none">
          {title}
        </h3>
      )}
      {children}
    </div>
  )
}

interface Group {
  id: NavGroup
  /** Always listed. */
  shown: NavItem[]
  /** Behind the `+N more` row. */
  hidden: NavItem[]
}

/** Whether `pathname` is on or below the destination of `item`. */
const isWithin = (pathname: string, item: NavItem) =>
  pathname === item.to || pathname.startsWith(`${item.to}/`)

export function SidebarNav({ collapsed = false }: { collapsed?: boolean }) {
  const { t } = useTranslation()
  const { data: types, isPending, isError, refetch, isFetching } = useTypes()
  const { data: caps } = useCapabilities()
  const { data: io } = useIoAccess()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const [favorites, toggleFavorite] = usePersistedSet(FAVORITES_KEY)
  const [adminOpen, toggleAdmin] = useAdminOpen()
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [filter, setFilter] = useState('')

  useEffect(() => {
    try {
      localStorage.removeItem(LEGACY_COLLAPSED_KEY)
    } catch {
      /* ignore */
    }
  }, [])

  const all = useMemo(() => (types ?? []).filter((x) => !HIDDEN_TYPES.has(x.name)), [types])
  const hasType = (name: string) => all.some((x) => x.name === name)

  const typeItem = (ty: TypeSummary): NavItem => {
    return {
      key: `type:${ty.name}`,
      to: '/types/$type',
      params: { type: ty.name },
      label: typeLabelPlural(t, ty),
      icon: <TypeIcon name={ty.icon} className="size-4 shrink-0" />,
      type: ty.name,
    }
  }
  const fixed = (key: string, to: NavPath, label: string, Icon: LucideIcon): NavItem => ({
    key,
    to,
    label,
    icon: <Icon className="size-4 shrink-0" aria-hidden />,
  })

  const groups = useMemo<Group[]>(() => {
    const listed = (g: NavGroup, nav: 'primary' | 'secondary') =>
      all
        .filter((x) => groupOf(x) === g && levelOf(x) === nav && !favorites.has(x.name))
        .map(typeItem)
    return NAV_GROUPS.flatMap((id) => {
      const primary = listed(id, 'primary')
      const secondary = listed(id, 'secondary')
      // Small groups list everything; a group with nothing primary promotes its secondary
      // types; a lone hidden row would cost as much as the link it hides.
      const full =
        primary.length === 0 ||
        primary.length + secondary.length <= GROUP_FULL_LIMIT ||
        secondary.length <= 1
      const group: Group = full
        ? { id, shown: [...primary, ...secondary], hidden: [] }
        : { id, shown: primary, hidden: secondary }
      return group.shown.length > 0 ? [group] : []
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, favorites, t])

  const adminItems = useMemo<NavItem[]>(
    () => [
      ...(caps?.acl ? [fixed('admin:access', '/admin/access', t('admin.nav.access'), ShieldCheck)] : []),
      ...(hasType('audit_event')
        ? [fixed('activity:audit', '/activity/audit', t('sidebar.auditLog'), History)]
        : []),
      ...(caps?.tasks ? [fixed('admin:tasks', '/admin/tasks', t('admin.nav.tasks'), ListChecks)] : []),
      ...(caps?.config
        ? [fixed('admin:config', '/admin/config', t('admin.nav.config'), SlidersHorizontal)]
        : []),
      ...(caps?.plugins ? [fixed('admin:plugins', '/admin/plugins', t('admin.nav.plugins'), Puzzle)] : []),
      ...(caps?.health ? [fixed('admin:health', '/admin/health', t('admin.nav.health'), HeartPulse)] : []),
      ...(io && (io.ldif_export || io.ldif_import || io.csv_import)
        ? [fixed('io', '/io', t('io.navLabel'), ArrowLeftRight)]
        : []),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [all, caps, io, t],
  )

  const favoriteItems = useMemo(
    () => all.filter((x) => favorites.has(x.name)).map(typeItem),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [all, favorites, t],
  )

  const dashboardItem = fixed('dashboard', '/', t('nav.dashboard'), LayoutDashboard)
  dashboardItem.exact = true

  const needle = filter.trim().toLowerCase()
  const visibleCount =
    1 +
    favoriteItems.length +
    adminItems.length +
    groups.reduce((n, g) => n + g.shown.length, 0)
  const showFilter = !collapsed && (visibleCount > FILTER_THRESHOLD || needle.length > 0)

  const renderItem = (item: NavItem) => (
    <NavLink
      key={item.key}
      item={item}
      collapsed={collapsed}
      pinned={!!item.type && favorites.has(item.type)}
      onTogglePin={toggleFavorite}
    />
  )

  const activeType = /^\/types\/([^/]+)/.exec(pathname)?.[1]
  const activeInAdmin = adminItems.some((i) => isWithin(pathname, i))
  const adminShown = collapsed || adminOpen || activeInAdmin

  const toggleExpanded = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (!next.delete(id)) next.add(id)
      return next
    })

  let body: ReactNode
  if (needle && !collapsed) {
    const pool = [
      dashboardItem,
      ...favoriteItems,
      ...groups.flatMap((g) => [...g.shown, ...g.hidden]),
      ...adminItems,
    ]
    const hits = pool.filter((i) => i.label.toLowerCase().includes(needle))
    body =
      hits.length > 0 ? (
        <div className="space-y-0.5 pt-2" data-testid="nav-filter-results">
          {hits.map(renderItem)}
        </div>
      ) : (
        <p className="px-3 pt-3 text-caption text-sidebar-muted" role="status">
          {t('sidebar.noMatches', { q: filter.trim() })}
        </p>
      )
  } else {
    body = (
      <>
        {favoriteItems.length > 0 && (
          <NavSection
            title={t('sidebar.favorites')}
            collapsed={collapsed}
            testId="nav-favorites"
            level="section"
          >
            {favoriteItems.map(renderItem)}
          </NavSection>
        )}

        {groups.length > 0 && (
          <div className="space-y-0.5" data-testid="nav-directory">
            {!collapsed && (
              <h2 className="label-caps px-3 pt-3 pb-0 text-sidebar-muted select-none">
                {t('sidebar.directory')}
              </h2>
            )}
            {groups.map((g) => {
              const activeHidden = g.hidden.some((i) => i.type === activeType)
              const showAll = expanded.has(g.id) || activeHidden
              const items = showAll ? [...g.shown, ...g.hidden] : g.shown
              return (
                <NavSection
                  key={g.id}
                  title={t(`sidebar.groups.${g.id}`)}
                  collapsed={collapsed}
                  testId={`nav-group-${g.id}`}
                >
                  {items.map(renderItem)}
                  {!collapsed && g.hidden.length > 0 && (
                    <button
                      type="button"
                      aria-expanded={showAll}
                      // The active type stays listed, so the row cannot fold it away.
                      aria-disabled={activeHidden || undefined}
                      onClick={() => !activeHidden && toggleExpanded(g.id)}
                      className={disclosureClass}
                    >
                      {showAll ? (
                        <ChevronDown className="size-3.5" aria-hidden />
                      ) : (
                        <ChevronRight className="size-3.5" aria-hidden />
                      )}
                      <span className="flex-1 text-left">
                        {showAll
                          ? t('sidebar.showFewer')
                          : t('sidebar.moreCount', { count: g.hidden.length })}
                      </span>
                    </button>
                  )}
                </NavSection>
              )
            })}
          </div>
        )}

        {adminItems.length > 0 && (
          <div className="space-y-0.5" data-testid="nav-admin">
            {collapsed ? (
              <div className="mx-1.5 my-1.5 h-px bg-sidebar-border" role="separator" />
            ) : (
              <h2 className="pt-3">
                <button
                  type="button"
                  onClick={() => !activeInAdmin && toggleAdmin()}
                  aria-expanded={adminShown}
                  aria-controls="nav-admin-items"
                  // On one of its pages the block cannot fold: the active link stays visible.
                  aria-disabled={activeInAdmin || undefined}
                  className="label-caps flex w-full items-center gap-1 rounded-md px-3 py-1 text-left text-sidebar-muted outline-none select-none hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {adminShown ? (
                    <ChevronDown className="size-3" aria-hidden />
                  ) : (
                    <ChevronRight className="size-3" aria-hidden />
                  )}
                  <span>{t('sidebar.administration')}</span>
                </button>
              </h2>
            )}
            {adminShown && (
              <div id="nav-admin-items" className="space-y-0.5">
                {adminItems.map(renderItem)}
              </div>
            )}
          </div>
        )}
      </>
    )
  }

  return (
    <nav aria-label={t('nav.main')} className="flex flex-col gap-1 p-2">
      <div className="space-y-0.5">{renderItem(dashboardItem)}</div>

      {showFilter && (
        <div className="relative mt-1">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-sidebar-muted"
            aria-hidden
          />
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t('sidebar.filterPlaceholder')}
            aria-label={t('sidebar.filter')}
            className="h-8 w-full rounded-md border border-sidebar-border bg-transparent pr-2 pl-8 text-caption text-sidebar-foreground outline-none placeholder:text-sidebar-muted focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
      )}

      {isPending && (
        <div className="space-y-2 px-1" aria-hidden>
          <Skeleton className="h-7 w-full bg-sidebar-accent" />
          <Skeleton className="h-7 w-full bg-sidebar-accent" />
          <Skeleton className="h-7 w-full bg-sidebar-accent" />
        </div>
      )}

      {isError && !types && (
        <div role="alert" className={cn('px-1', collapsed && 'flex justify-center')}>
          {collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={() => void refetch()}
                  disabled={isFetching}
                  aria-label={`${t('sidebar.loadError')} ${t('sidebar.retry')}`}
                  className="flex size-8 items-center justify-center rounded-md text-sidebar-muted outline-none hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <RotateCw className="size-4" aria-hidden />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right" sideOffset={8}>
                {t('sidebar.loadError')} {t('sidebar.retry')}
              </TooltipContent>
            </Tooltip>
          ) : (
            <div className="flex items-center gap-2 rounded-md border border-sidebar-border px-2 py-1.5 text-caption text-sidebar-muted">
              <span className="flex-1">{t('sidebar.loadError')}</span>
              <button
                type="button"
                onClick={() => void refetch()}
                disabled={isFetching}
                className="flex items-center gap-1 rounded-sm px-1 py-0.5 font-medium text-sidebar-foreground outline-none hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
              >
                <RotateCw className="size-3" aria-hidden />
                {t('sidebar.retry')}
              </button>
            </div>
          )}
        </div>
      )}

      {body}
    </nav>
  )
}

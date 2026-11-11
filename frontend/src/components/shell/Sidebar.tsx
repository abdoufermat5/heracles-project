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
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Star,
  type LucideIcon,
} from 'lucide-react'
import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useDashboard, useTypes } from '@/api/hooks'
import { NAV_GROUPS, type NavGroup, type TypeSummary } from '@/api/types'
import { useCapabilities } from '@/features/admin/hooks'
import { useIoAccess } from '@/features/io/hooks'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { TypeIcon } from '@/lib/icons'
import { cn } from '@/lib/utils'

const linkBaseClass =
  'group relative flex h-9 min-w-0 flex-1 items-center gap-2.5 rounded-md px-3 text-body font-medium text-sidebar-foreground transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-sidebar hover:bg-sidebar-accent hover:text-sidebar-accent-foreground [&_svg]:opacity-80'
const activeClass =
  'bg-sidebar-accent text-sidebar-accent-foreground! font-medium before:absolute before:top-1.5 before:bottom-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-sidebar-signal'

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

const COLLAPSED_KEY = 'heracles.nav.collapsedGroups'
const FAVORITES_KEY = 'heracles.nav.favorites'
/** Show the filter input once more links than this are visible. */
const FILTER_THRESHOLD = 15

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

// ------------------------------------------------------------------- the model

interface NavItem {
  key: string
  to: NavPath
  params?: { type: string }
  label: string
  icon: ReactNode
  count?: number | null
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
  const { label, count } = item
  const link = (
    <Link
      to={item.to as never}
      params={item.params as never}
      activeOptions={{ exact: item.exact }}
      className={cn(linkBaseClass, collapsed && 'mx-auto size-8 flex-none justify-center px-0')}
      activeProps={{ className: activeClass, 'aria-current': 'page' }}
      aria-label={collapsed ? label : undefined}
    >
      {item.icon}
      {!collapsed && (
        <>
          <span className="flex-1 truncate">{label}</span>
          {typeof count === 'number' && (
            <span className="ml-auto font-mono text-caption tabular-nums text-sidebar-muted group-hover:text-sidebar-accent-foreground">
              {count.toLocaleString()}
            </span>
          )}
        </>
      )}
    </Link>
  )

  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>{link}</TooltipTrigger>
        <TooltipContent side="right" sideOffset={8} className="flex items-center gap-1.5">
          <span>{label}</span>
          {typeof count === 'number' && (
            <span className="font-mono text-caption tabular-nums opacity-70">
              {count.toLocaleString()}
            </span>
          )}
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
          'absolute top-1/2 right-1 -translate-y-1/2 rounded-sm bg-sidebar p-1 text-sidebar-muted outline-none hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring',
          pinned ? 'opacity-100' : 'opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100',
        )}
      >
        <Star className={cn('size-3.5', pinned && 'fill-current')} aria-hidden />
      </button>
    </div>
  )
}

function NavSection({
  id,
  title,
  collapsed,
  open,
  onToggle,
  children,
  testId,
}: {
  id: string
  title: string
  collapsed: boolean
  /** Collapsible when `onToggle` is given. */
  open: boolean
  onToggle?: (id: string) => void
  children: ReactNode
  testId?: string
}) {
  const { t } = useTranslation()
  return (
    <div className="space-y-0.5" data-testid={testId ?? `nav-group-${id}`}>
      {collapsed ? (
        <div className="mx-1.5 my-1.5 h-px bg-sidebar-border" role="separator" />
      ) : onToggle ? (
        <h2 className="pt-3 pb-1">
          <button
            type="button"
            onClick={() => onToggle(id)}
            aria-expanded={open}
            aria-label={t('sidebar.toggleGroup', { group: title })}
            className="label-caps flex w-full items-center gap-1 rounded-sm px-3 py-0.5 text-left text-sidebar-muted outline-none select-none hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            {open ? (
              <ChevronDown className="size-3" aria-hidden />
            ) : (
              <ChevronRight className="size-3" aria-hidden />
            )}
            <span>{title}</span>
          </button>
        </h2>
      ) : (
        <h2 className="label-caps px-3 pt-4 pb-1.5 text-sidebar-muted select-none">{title}</h2>
      )}
      {(collapsed || open) && children}
    </div>
  )
}

interface Group {
  id: NavGroup
  primary: NavItem[]
  more: NavItem[]
}

export function SidebarNav({ collapsed = false }: { collapsed?: boolean }) {
  const { t } = useTranslation()
  const { data: types, isPending } = useTypes()
  const { data: dashboard } = useDashboard()
  const { data: caps } = useCapabilities()
  const { data: io } = useIoAccess()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const [closed, toggleGroup] = usePersistedSet(COLLAPSED_KEY)
  const [favorites, toggleFavorite] = usePersistedSet(FAVORITES_KEY)
  const [moreOpen, setMoreOpen] = useState<Set<string>>(() => new Set())
  const [filter, setFilter] = useState('')

  const all = useMemo(() => types ?? [], [types])
  const hasType = (name: string) => all.some((x) => x.name === name)

  const typeItem = (ty: TypeSummary): NavItem => {
    const card = ty.count_key ? dashboard?.cards?.find((c) => c.key === ty.count_key) : undefined
    return {
      key: `type:${ty.name}`,
      to: '/types/$type',
      params: { type: ty.name },
      label: ty.label_plural,
      icon: <TypeIcon name={ty.icon} className="size-4 shrink-0" />,
      count: card ? card.value : null,
      type: ty.name,
    }
  }
  const fixed = (
    key: string,
    to: NavPath,
    label: string,
    Icon: LucideIcon,
  ): NavItem => ({ key, to, label, icon: <Icon className="size-4 shrink-0" aria-hidden /> })

  const groups = useMemo<Group[]>(() => {
    const byGroup = (g: NavGroup, nav: 'primary' | 'secondary') =>
      all
        .filter((x) => x.nav_group === g && x.nav === nav && !favorites.has(x.name))
        .map(typeItem)
    const extra: Record<NavGroup, NavItem[]> = {
      people: [],
      organization: [],
      access: caps?.acl
        ? [fixed('admin:access', '/admin/access', t('admin.nav.access'), ShieldCheck)]
        : [],
      infrastructure: [],
      mail: [],
      activity: [
        ...(hasType('audit_event')
          ? [fixed('activity:audit', '/activity/audit', t('sidebar.auditLog'), History)]
          : []),
        ...(caps?.tasks ? [fixed('admin:tasks', '/admin/tasks', t('admin.nav.tasks'), ListChecks)] : []),
      ],
      settings: [
        ...(caps?.config
          ? [fixed('admin:config', '/admin/config', t('admin.nav.config'), SlidersHorizontal)]
          : []),
        ...(caps?.plugins ? [fixed('admin:plugins', '/admin/plugins', t('admin.nav.plugins'), Puzzle)] : []),
        ...(caps?.health ? [fixed('admin:health', '/admin/health', t('admin.nav.health'), HeartPulse)] : []),
        ...(io && (io.ldif_export || io.ldif_import || io.csv_import)
          ? [fixed('io', '/io', t('io.navLabel'), ArrowLeftRight)]
          : []),
      ],
    } as Record<NavGroup, NavItem[]>
    return NAV_GROUPS.map((id) => ({
      id,
      primary: [...byGroup(id, 'primary'), ...extra[id]],
      more: byGroup(id, 'secondary'),
    })).filter((g) => g.primary.length + g.more.length > 0)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, favorites, dashboard, caps, io, t])

  const favoriteItems = useMemo(
    () => all.filter((x) => favorites.has(x.name)).map(typeItem),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [all, favorites, dashboard],
  )

  const dashboardItem = fixed('dashboard', '/', t('nav.dashboard'), LayoutDashboard)
  dashboardItem.exact = true

  const needle = filter.trim().toLowerCase()
  const visibleCount =
    1 + favoriteItems.length + groups.reduce((n, g) => n + g.primary.length, 0)
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
  const groupTitle = (id: NavGroup) => t(`sidebar.groups.${id}`)

  let body: ReactNode
  if (needle && !collapsed) {
    const pool = [
      dashboardItem,
      ...favoriteItems,
      ...groups.flatMap((g) => [...g.primary, ...g.more]),
    ]
    const hits = pool.filter((i) => i.label.toLowerCase().includes(needle))
    body =
      hits.length > 0 ? (
        <div className="space-y-0.5 pt-2" data-testid="nav-filter-results">
          {hits.map(renderItem)}
        </div>
      ) : (
        <p className="px-3 pt-3 text-caption text-sidebar-muted">
          {t('sidebar.noMatches', { q: filter.trim() })}
        </p>
      )
  } else {
    body = (
      <>
        {favoriteItems.length > 0 && (
          <NavSection
            id="favorites"
            title={t('sidebar.favorites')}
            collapsed={collapsed}
            open
            testId="nav-favorites"
          >
            {favoriteItems.map(renderItem)}
          </NavSection>
        )}
        {groups.map((g) => {
          const open = collapsed || !closed.has(g.id)
          const activeInMore = g.more.some((i) => i.type === activeType)
          const moreShown = moreOpen.has(g.id) || activeInMore
          return (
            <NavSection
              key={g.id}
              id={g.id}
              title={groupTitle(g.id)}
              collapsed={collapsed}
              open={open}
              onToggle={toggleGroup}
            >
              {g.primary.map(renderItem)}
              {!collapsed && g.more.length > 0 && (
                <>
                  <button
                    type="button"
                    aria-expanded={moreShown}
                    onClick={() =>
                      setMoreOpen((prev) => {
                        const next = new Set(prev)
                        if (!next.delete(g.id)) next.add(g.id)
                        return next
                      })
                    }
                    className="flex h-8 w-full items-center gap-2.5 rounded-md px-3 text-caption font-medium text-sidebar-muted outline-none hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {moreShown ? (
                      <ChevronDown className="size-3.5" aria-hidden />
                    ) : (
                      <ChevronRight className="size-3.5" aria-hidden />
                    )}
                    <span className="flex-1 text-left">{t('sidebar.more')}</span>
                    <span className="font-mono tabular-nums">{g.more.length}</span>
                  </button>
                  {moreShown && <div className="space-y-0.5 pl-2">{g.more.map(renderItem)}</div>}
                </>
              )}
            </NavSection>
          )
        })}
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
        <div className="space-y-2 px-1">
          <Skeleton className="h-7 w-full bg-sidebar-accent" />
          <Skeleton className="h-7 w-full bg-sidebar-accent" />
          <Skeleton className="h-7 w-full bg-sidebar-accent" />
        </div>
      )}

      {body}
    </nav>
  )
}

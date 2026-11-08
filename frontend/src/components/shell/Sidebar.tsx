import { Link } from '@tanstack/react-router'
import {
  ArrowLeftRight,
  HeartPulse,
  LayoutDashboard,
  ListChecks,
  Puzzle,
  ShieldCheck,
  SlidersHorizontal,
  type LucideIcon,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useDashboard, useTypes } from '@/api/hooks'
import { CATEGORIES, type TypeSummary } from '@/api/types'
import { useCapabilities } from '@/features/admin/hooks'
import { useIoAccess } from '@/features/io/hooks'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { TypeIcon } from '@/lib/icons'
import { cn } from '@/lib/utils'

const linkBaseClass =
  'group relative flex h-9 items-center gap-2.5 rounded-md px-3 text-body font-medium text-sidebar-foreground transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-sidebar hover:bg-sidebar-accent hover:text-sidebar-accent-foreground [&_svg]:opacity-80'
const activeClass =
  'bg-sidebar-accent text-sidebar-accent-foreground! font-medium before:absolute before:top-1.5 before:bottom-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-sidebar-signal'

function NavLink({
  collapsed,
  label,
  count,
  children,
  to,
  params,
  exact,
}: {
  collapsed: boolean
  label: string
  count?: number | null
  children: React.ReactNode
  to: '/' | '/types/$type' | AdminPath | '/io'
  params?: { type: string }
  exact?: boolean
}) {
  const el = (
    <Link
      to={to}
      params={params as never}
      activeOptions={{ exact }}
      className={cn(linkBaseClass, collapsed && 'mx-auto size-8 justify-center px-0')}
      activeProps={{ className: activeClass, 'aria-current': 'page' }}
      aria-label={collapsed ? label : undefined}
    >
      {children}
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

  if (!collapsed) return el

  return (
    <Tooltip>
      <TooltipTrigger asChild>{el}</TooltipTrigger>
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

/** Object types people manage day to day; the rest of "directory" is organisation. */
const PEOPLE_TYPES = new Set(['user', 'group'])

function NavSection({
  title,
  collapsed,
  children,
  testId,
}: {
  title: string
  collapsed: boolean
  children: React.ReactNode
  testId?: string
}) {
  return (
    <div className="space-y-0.5" data-testid={testId}>
      {!collapsed ? (
        <h2 className="label-caps px-3 pt-4 pb-1.5 text-sidebar-muted select-none">{title}</h2>
      ) : (
        <div className="mx-1.5 my-1.5 h-px bg-sidebar-border" role="separator" />
      )}
      {children}
    </div>
  )
}

export function SidebarNav({ collapsed = false }: { collapsed?: boolean }) {
  const { t } = useTranslation()
  const { data: types, isPending } = useTypes()
  const { data: dashboard } = useDashboard()
  const { data: caps } = useCapabilities()
  const { data: io } = useIoAccess()

  const countFor = (name: string): number | null => {
    if (!dashboard?.cards) return null
    const card = dashboard.cards.find(
      (c) =>
        c.key === name ||
        c.key === `${name}s` ||
        (name === 'department' && c.key === 'departments') ||
        (name === 'dns_zone' && c.key === 'dns_zones'),
    )
    return card ? card.value : null
  }

  const typeLink = (ty: TypeSummary) => (
    <NavLink
      key={ty.name}
      to="/types/$type"
      params={{ type: ty.name }}
      collapsed={collapsed}
      label={ty.label_plural}
      count={countFor(ty.name)}
    >
      <TypeIcon name={ty.icon} className="size-4 shrink-0" />
    </NavLink>
  )

  const all = types ?? []
  const people = all.filter((x) => x.category === 'directory' && PEOPLE_TYPES.has(x.name))
  const organization = all.filter((x) => x.category === 'directory' && !PEOPLE_TYPES.has(x.name))
  const access = all.filter((x) => x.category === 'access')
  const others = CATEGORIES.filter((c) => c !== 'directory' && c !== 'access')

  const admin: { to: AdminPath | '/io'; label: string; Icon: LucideIcon; show: boolean }[] = [
    { to: '/admin/config', label: t('admin.nav.config'), Icon: SlidersHorizontal, show: !!caps?.config },
    { to: '/admin/health', label: t('admin.nav.health'), Icon: HeartPulse, show: !!caps?.health },
    { to: '/admin/tasks', label: t('admin.nav.tasks'), Icon: ListChecks, show: !!caps?.tasks },
    { to: '/admin/plugins', label: t('admin.nav.plugins'), Icon: Puzzle, show: !!caps?.plugins },
    {
      to: '/io',
      label: t('io.navLabel'),
      Icon: ArrowLeftRight,
      show: !!io && (io.ldif_export || io.ldif_import || io.csv_import),
    },
  ]
  const adminVisible = admin.filter((i) => i.show)

  return (
    <nav aria-label={t('nav.main')} className="flex flex-col gap-3 p-2">
      <div className="space-y-0.5">
        <NavLink to="/" exact collapsed={collapsed} label={t('nav.dashboard')}>
          <LayoutDashboard className="size-4 shrink-0" aria-hidden />
        </NavLink>
      </div>

      {isPending && (
        <div className="space-y-2 px-1">
          <Skeleton className="h-7 w-full bg-sidebar-accent" />
          <Skeleton className="h-7 w-full bg-sidebar-accent" />
          <Skeleton className="h-7 w-full bg-sidebar-accent" />
        </div>
      )}

      {people.length > 0 && (
        <NavSection title={t('nav.people')} collapsed={collapsed}>
          {people.map(typeLink)}
        </NavSection>
      )}
      {organization.length > 0 && (
        <NavSection title={t('nav.organization')} collapsed={collapsed}>
          {organization.map(typeLink)}
        </NavSection>
      )}
      {(access.length > 0 || caps?.acl) && (
        <NavSection title={t('categories.access')} collapsed={collapsed}>
          {access.map(typeLink)}
          {caps?.acl && (
            <NavLink to="/admin/access" collapsed={collapsed} label={t('admin.nav.access')}>
              <ShieldCheck className="size-4 shrink-0" aria-hidden />
            </NavLink>
          )}
        </NavSection>
      )}
      {others.map((cat) => {
        const items = all.filter((x) => x.category === cat)
        if (items.length === 0) return null
        return (
          <NavSection key={cat} title={t(`categories.${cat}`)} collapsed={collapsed}>
            {items.map(typeLink)}
          </NavSection>
        )
      })}
      {adminVisible.length > 0 && (
        <NavSection title={t('admin.nav.group')} collapsed={collapsed} testId="admin-nav">
          {adminVisible.map(({ to, label, Icon }) => (
            <NavLink key={to} to={to} collapsed={collapsed} label={label}>
              <Icon className="size-4 shrink-0" aria-hidden />
            </NavLink>
          ))}
        </NavSection>
      )}
    </nav>
  )
}

// --- P3 admin ---
type AdminPath =
  | '/admin/access'
  | '/admin/config'
  | '/admin/health'
  | '/admin/plugins'
  | '/admin/tasks'

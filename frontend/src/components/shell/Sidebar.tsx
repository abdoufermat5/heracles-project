import { Link } from '@tanstack/react-router'
import { LayoutDashboard } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useDashboard, useTypes } from '@/api/hooks'
import { CATEGORIES } from '@/api/types'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { TypeIcon } from '@/lib/icons'
import { cn } from '@/lib/utils'

const linkBaseClass =
  'group relative flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-xs md:text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-sidebar text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground'
const activeClass =
  'bg-primary-soft !text-foreground font-semibold shadow-xs ring-1 ring-primary/25 dark:bg-primary-soft/80'

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
  to: '/' | '/types/$type'
  params?: { type: string }
  exact?: boolean
}) {
  const el = (
    <Link
      to={to}
      params={params as never}
      activeOptions={{ exact }}
      className={cn(linkBaseClass, collapsed && 'justify-center px-0 size-8 mx-auto')}
      activeProps={{ className: activeClass, 'aria-current': 'page' }}
      aria-label={collapsed ? label : undefined}
    >
      {children}
      {!collapsed && (
        <>
          <span className="truncate flex-1">{label}</span>
          {typeof count === 'number' && (
            <span className="ml-auto rounded-full bg-muted/60 px-1.5 py-0.2 text-[10px] font-mono font-normal tabular-nums text-muted-foreground group-hover:bg-muted group-hover:text-foreground">
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
          <span className="rounded bg-muted/80 px-1 py-0.2 text-[10px] font-mono tabular-nums text-muted-foreground">
            {count.toLocaleString()}
          </span>
        )}
      </TooltipContent>
    </Tooltip>
  )
}

export function SidebarNav({ collapsed = false }: { collapsed?: boolean }) {
  const { t } = useTranslation()
  const { data: types, isPending } = useTypes()
  const { data: dashboard } = useDashboard()

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

  return (
    <nav aria-label={t('nav.main')} className="flex flex-col gap-3 p-2">
      <div className="space-y-0.5">
        <NavLink to="/" exact collapsed={collapsed} label={t('nav.dashboard')}>
          <LayoutDashboard className="size-4 shrink-0" aria-hidden />
        </NavLink>
      </div>

      {isPending && (
        <div className="space-y-2 px-1">
          <Skeleton className="h-7 w-full" />
          <Skeleton className="h-7 w-full" />
          <Skeleton className="h-7 w-full" />
        </div>
      )}

      {CATEGORIES.map((cat) => {
        const items = types?.filter((x) => x.category === cat) ?? []
        if (items.length === 0) return null
        return (
          <div key={cat} className="space-y-0.5">
            {!collapsed ? (
              <h2 className="px-2.5 pt-2 pb-1 text-[10px] font-semibold tracking-wider uppercase text-muted-foreground/70 select-none">
                {t(`categories.${cat}`)}
              </h2>
            ) : (
              <div className="bg-border/60 mx-1.5 my-1.5 h-px" role="separator" />
            )}
            {items.map((ty) => (
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
            ))}
          </div>
        )
      })}
    </nav>
  )
}

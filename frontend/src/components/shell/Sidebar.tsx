import { Link } from '@tanstack/react-router'
import { LayoutDashboard } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useTypes } from '@/api/hooks'
import { CATEGORIES } from '@/api/types'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { TypeIcon } from '@/lib/icons'
import { cn } from '@/lib/utils'

const linkClass =
  'text-muted-foreground hover:bg-accent hover:text-foreground flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium'
const activeClass = 'bg-primary-soft !text-foreground'

function NavLink({
  collapsed,
  label,
  children,
  to,
  params,
  exact,
}: {
  collapsed: boolean
  label: string
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
      className={cn(linkClass, collapsed && 'justify-center px-0')}
      activeProps={{ className: activeClass, 'aria-current': 'page' }}
      aria-label={collapsed ? label : undefined}
    >
      {children}
      {!collapsed && <span className="truncate">{label}</span>}
    </Link>
  )
  if (!collapsed) return el
  return (
    <Tooltip>
      <TooltipTrigger asChild>{el}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  )
}

export function SidebarNav({ collapsed = false }: { collapsed?: boolean }) {
  const { t } = useTranslation()
  const { data: types, isPending } = useTypes()

  return (
    <nav aria-label={t('nav.main')} className="flex flex-col gap-4 p-2">
      <NavLink to="/" exact collapsed={collapsed} label={t('nav.dashboard')}>
        <LayoutDashboard className="size-4 shrink-0" aria-hidden />
      </NavLink>
      {isPending && (
        <div className="space-y-2 px-2">
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
              <h2 className="text-muted-foreground px-2.5 pb-1 text-[11px] font-semibold tracking-wider uppercase">
                {t(`categories.${cat}`)}
              </h2>
            ) : (
              <div className="bg-border mx-2 my-1 h-px" role="separator" />
            )}
            {items.map((ty) => (
              <NavLink
                key={ty.name}
                to="/types/$type"
                params={{ type: ty.name }}
                collapsed={collapsed}
                label={ty.label_plural}
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

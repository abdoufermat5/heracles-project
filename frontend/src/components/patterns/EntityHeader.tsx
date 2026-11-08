import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { cn, initials } from '@/lib/utils'

export interface EntityMeta {
  icon?: React.ReactNode
  content: React.ReactNode
}

/**
 * Header of a record page: who or what this is, its state, the facts people look
 * for first and the actions they take most.
 */
export function EntityHeader({
  name,
  subtitle,
  avatarUrl,
  icon,
  badges,
  meta = [],
  actions,
  breadcrumbs,
  className,
}: {
  name: string
  subtitle?: React.ReactNode
  avatarUrl?: string | null
  /** Shown instead of initials for non-person entries (group, department, ...). */
  icon?: React.ReactNode
  badges?: React.ReactNode
  meta?: EntityMeta[]
  actions?: React.ReactNode
  breadcrumbs?: React.ReactNode
  className?: string
}) {
  return (
    <header data-slot="entity-header" className={cn('flex flex-col gap-3 pb-5', className)}>
      {breadcrumbs}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          {icon ? (
            <div className="flex size-14 shrink-0 items-center justify-center rounded-xl border bg-card text-muted-foreground [&>svg]:size-6">
              {icon}
            </div>
          ) : (
            <Avatar className="size-14 text-lead">
              {avatarUrl && <AvatarImage src={avatarUrl} alt="" />}
              <AvatarFallback className="bg-primary-soft font-semibold text-primary">
                {initials(name)}
              </AvatarFallback>
            </Avatar>
          )}
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-title font-semibold tracking-tight text-foreground">
                {name}
              </h1>
              {badges}
            </div>
            {subtitle && <p className="text-body text-muted-foreground">{subtitle}</p>}
            {meta.length > 0 && (
              <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-0.5 text-small text-muted-foreground">
                {meta.map((m, i) => (
                  <li key={i} className="flex min-w-0 items-center gap-1.5 [&>svg]:size-3.5 [&>svg]:shrink-0">
                    {m.icon}
                    <span className="min-w-0 truncate">{m.content}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  )
}

import { cn } from '@/lib/utils'

type LogoProps = {
  collapsed?: boolean
  className?: string
  tone?: 'default' | 'inverse'
}

/** Heracles mark: a hexagon (the club's strength) split by an H-shaped bridge. */
export function LogoMark({
  className,
  tone = 'default',
}: {
  className?: string
  tone?: 'default' | 'inverse'
}) {
  return (
    <svg
      viewBox="0 0 32 32"
      role="img"
      aria-label="Heracles"
      className={cn('size-6', className)}
      fill="none"
    >
      <path
        d="M16 2.5 27.7 9.25v13.5L16 29.5 4.3 22.75V9.25L16 2.5Z"
        className={tone === 'inverse' ? 'fill-sidebar-accent-foreground' : 'fill-primary'}
      />
      <path
        d="M11.5 10v12M20.5 10v12M11.5 16h9"
        className={tone === 'inverse' ? 'stroke-sidebar' : 'stroke-primary-foreground'}
        strokeWidth="2.6"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function Logo({ collapsed = false, className, tone = 'default' }: LogoProps) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <LogoMark tone={tone} />
      {!collapsed && (
        <span
          className={cn(
            'text-[15px] font-semibold tracking-tight',
            tone === 'inverse' && 'text-sidebar-accent-foreground',
          )}
        >
          Heracles
        </span>
      )}
    </div>
  )
}

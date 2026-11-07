import { cn } from '@/lib/utils'

/** Heracles mark: a hexagon (the club's strength) split by an H-shaped bridge. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      role="img"
      aria-label="Heracles"
      className={cn('size-7', className)}
      fill="none"
    >
      <path
        d="M16 2.5 27.7 9.25v13.5L16 29.5 4.3 22.75V9.25L16 2.5Z"
        className="fill-primary"
      />
      <path
        d="M11.5 10v12M20.5 10v12M11.5 16h9"
        className="stroke-primary-foreground"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function Logo({ collapsed = false, className }: { collapsed?: boolean; className?: string }) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <LogoMark />
      {!collapsed && <span className="text-base font-semibold tracking-tight">Heracles</span>}
    </div>
  )
}

import * as React from "react"
import { cn } from "@/lib/utils"

export interface EmptyStateProps extends React.ComponentProps<"div"> {
  icon: React.ReactNode
  title: string
  description?: React.ReactNode
  action?: React.ReactNode
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div
      role="status"
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed border-border/80 bg-card/40 px-6 py-12 text-center",
        className
      )}
      {...props}
    >
      <div className="flex size-11 items-center justify-center rounded-full bg-muted/80 text-muted-foreground shadow-xs ring-1 ring-border/50 [&>svg]:size-5">
        {icon}
      </div>
      <div className="mt-3.5 max-w-sm space-y-1">
        <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
        {description && (
          <p className="text-xs text-muted-foreground leading-relaxed">{description}</p>
        )}
      </div>
      {action && <div className="mt-4 flex items-center gap-2">{action}</div>}
    </div>
  )
}

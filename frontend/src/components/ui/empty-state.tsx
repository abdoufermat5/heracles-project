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
        "flex flex-col items-center justify-center rounded-md border border-dashed border-border bg-card px-6 py-10 text-center",
        className
      )}
      {...props}
    >
      <div className="text-muted-foreground [&>svg]:size-5 [&>svg]:opacity-80">{icon}</div>
      <div className="mt-2.5 max-w-sm space-y-1">
        <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
        {description && (
          <p className="text-body leading-relaxed text-muted-foreground">{description}</p>
        )}
      </div>
      {action && <div className="mt-4 flex items-center gap-2">{action}</div>}
    </div>
  )
}

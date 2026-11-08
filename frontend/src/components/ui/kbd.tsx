import * as React from "react"
import { cn } from "@/lib/utils"

export interface KbdProps extends React.ComponentProps<"kbd"> {
  keys?: string[]
}

export function Kbd({ className, children, keys, ...props }: KbdProps) {
  if (keys && keys.length > 0) {
    return (
      <span className={cn("inline-flex items-center gap-0.5", className)}>
        {keys.map((k, i) => (
          <kbd
            key={i}
            className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-border bg-muted px-1.5 font-mono text-[11px] font-medium text-muted-foreground shadow-xs select-none dark:border-border/60"
            {...props}
          >
            {k}
          </kbd>
        ))}
      </span>
    )
  }

  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded border border-border bg-muted px-1.5 font-mono text-[11px] font-medium text-muted-foreground shadow-xs select-none dark:border-border/60",
        className
      )}
      {...props}
    >
      {children}
    </kbd>
  )
}

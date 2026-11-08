import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-sm border px-1.5 text-[11px] font-medium whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 aria-invalid:border-destructive aria-invalid:ring-destructive/20 [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      variant: {
        default: "h-5 border-transparent bg-primary text-primary-foreground [a&]:hover:bg-primary/90",
        primary: "h-5 border-transparent bg-primary text-primary-foreground [a&]:hover:bg-primary/90",
        neutral: "h-5 border-border bg-muted text-muted-foreground [a&]:hover:bg-muted/80",
        secondary: "h-5 border-transparent bg-secondary text-secondary-foreground [a&]:hover:bg-secondary/80",
        success: "h-5 border-success/25 bg-success-soft text-success [a&]:hover:bg-success-soft/80",
        warning: "h-5 border-warning/30 bg-warning-soft text-warning [a&]:hover:bg-warning-soft/80",
        destructive:
          "h-5 border-destructive/30 bg-destructive-soft text-destructive focus-visible:ring-destructive/20 [a&]:hover:bg-destructive-soft/80",
        outline:
          "h-5 border-border bg-transparent text-foreground [a&]:hover:bg-accent [a&]:hover:text-accent-foreground",
        ghost: "h-5 border-transparent [a&]:hover:bg-accent [a&]:hover:text-accent-foreground",
        link: "h-5 border-transparent text-primary underline-offset-4 [a&]:hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }

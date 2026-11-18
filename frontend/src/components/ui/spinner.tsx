import * as React from "react"
import { Loader2 } from "lucide-react"
import { useTranslation } from "react-i18next"
import { cn } from "@/lib/utils"

export interface SpinnerProps extends React.ComponentProps<"svg"> {
  size?: "sm" | "default" | "lg"
}

export function Spinner({ className, size = "default", ...props }: SpinnerProps) {
  const { t } = useTranslation()
  const sizeClasses = {
    sm: "size-3.5",
    default: "size-4",
    lg: "size-6",
  }

  return (
    <Loader2
      role="status"
      aria-label={t("common.loading")}
      className={cn("animate-spin text-muted-foreground", sizeClasses[size], className)}
      {...props}
    />
  )
}

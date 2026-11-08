import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

export type AccountStatus = 'active' | 'locked' | 'expired' | 'disabled' | 'pending'

const TONE: Record<AccountStatus, string> = {
  active: 'border-success/25 bg-success-soft text-success',
  locked: 'border-warning/30 bg-warning-soft text-warning',
  expired: 'border-warning/30 bg-warning-soft text-warning',
  disabled: 'border-border bg-muted text-muted-foreground',
  pending: 'border-primary/20 bg-primary-soft text-primary',
}

const DOT: Record<AccountStatus, string> = {
  active: 'bg-success',
  locked: 'bg-warning',
  expired: 'bg-warning',
  disabled: 'bg-muted-foreground',
  pending: 'bg-primary',
}

/** The state of an account in plain words, with a colour reserved for that state. */
export function StatusBadge({
  status,
  className,
}: {
  status: AccountStatus
  className?: string
}) {
  const { t } = useTranslation()
  return (
    <span
      data-status={status}
      className={cn(
        'inline-flex h-6 items-center gap-1.5 rounded-full border px-2 text-caption font-medium whitespace-nowrap',
        TONE[status],
        className,
      )}
    >
      <span className={cn('size-1.5 rounded-full', DOT[status])} aria-hidden />
      {t(`status.${status}`)}
    </span>
  )
}

import { AlertCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { isApiError } from '@/api/client'
import { Button } from '@/components/ui/button'

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation()
  const message = isApiError(error) ? error.message : t('common.error')
  const notFound = isApiError(error) && error.status === 404
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-16 text-center"
    >
      <AlertCircle className="text-destructive size-8" aria-hidden />
      <div>
        <p className="font-medium">{notFound ? t('common.notFound') : t('common.errorTitle')}</p>
        <p className="text-muted-foreground text-sm">{message}</p>
      </div>
      {onRetry && !notFound && (
        <Button variant="outline" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: React.ReactNode
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-16 text-center">
      <div className="text-muted-foreground">{icon}</div>
      <div>
        <p className="font-medium">{title}</p>
        {description && <p className="text-muted-foreground text-sm">{description}</p>}
      </div>
      {action}
    </div>
  )
}

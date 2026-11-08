import { AlertCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { isApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'

export { EmptyState }

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation()
  const message = isApiError(error) ? error.message : t('common.error')
  const notFound = isApiError(error) && error.status === 404
  return (
    <div
      role="alert"
      className="rounded-md border border-border bg-card px-4 py-4"
    >
      <div className="flex items-start gap-2.5">
        <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-semibold tracking-tight text-foreground">
            {notFound ? t('common.notFound') : t('common.errorTitle')}
          </p>
          <p className="text-body leading-relaxed text-muted-foreground">{message}</p>
          {onRetry && !notFound && (
            <div className="pt-2">
              <Button variant="outline" size="sm" onClick={onRetry}>
                {t('common.retry')}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

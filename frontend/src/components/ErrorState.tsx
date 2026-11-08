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
      className="flex flex-col items-center justify-center rounded-lg border border-dashed border-destructive/40 bg-destructive/5 px-6 py-12 text-center"
    >
      <div className="flex size-11 items-center justify-center rounded-full bg-destructive/10 text-destructive shadow-xs ring-1 ring-destructive/20">
        <AlertCircle className="size-5" aria-hidden />
      </div>
      <div className="mt-3.5 max-w-sm space-y-1">
        <p className="text-sm font-semibold tracking-tight text-foreground">
          {notFound ? t('common.notFound') : t('common.errorTitle')}
        </p>
        <p className="text-xs text-muted-foreground leading-relaxed">{message}</p>
      </div>
      {onRetry && !notFound && (
        <div className="mt-4">
          <Button variant="outline" size="sm" onClick={onRetry}>
            {t('common.retry')}
          </Button>
        </div>
      )}
    </div>
  )
}

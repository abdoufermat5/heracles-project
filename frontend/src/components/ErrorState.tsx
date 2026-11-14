import { AlertCircle } from 'lucide-react'
import { useRouter } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { describeError } from '@/components/resilience/describeError'

export { EmptyState }

/**
 * Where to go from an error: back to the previous page, or to the dashboard. Rendered
 * only inside the router, so a stand-alone render (tests, a boundary above the router)
 * simply has no navigation.
 */
export function ErrorNavigation() {
  const { t } = useTranslation()
  const router = useRouter({ warn: false }) as ReturnType<typeof useRouter> | undefined
  if (!router) return null
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => router.history.back()}>
        {t('resilience.back')}
      </Button>
      <Button variant="outline" size="sm" onClick={() => void router.navigate({ to: '/' })}>
        {t('resilience.dashboard')}
      </Button>
    </>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation()
  const d = describeError(t, error)
  return (
    <div role="alert" className="rounded-md border border-border bg-card px-4 py-4">
      <div className="flex items-start gap-2.5">
        <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-semibold tracking-tight text-foreground">{d.title}</p>
          <p className="text-body leading-relaxed text-muted-foreground">{d.body}</p>
          {d.detail && d.detail !== d.body && (
            <p className="break-words font-mono text-caption text-muted-foreground/80">{d.detail}</p>
          )}
          <div className="flex flex-wrap gap-2 pt-2">
            {onRetry && !d.notFound && (
              <Button variant="outline" size="sm" onClick={onRetry}>
                {t('common.retry')}
              </Button>
            )}
            <ErrorNavigation />
          </div>
        </div>
      </div>
    </div>
  )
}

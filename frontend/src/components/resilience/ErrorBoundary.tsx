import { AlertCircle } from 'lucide-react'
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { ErrorNavigation } from '@/components/ErrorState'
import { Button } from '@/components/ui/button'
import { describeError } from './describeError'

/** Plain-text report of an error, for the "Copy details" button. */
export function errorReport(error: unknown): string {
  const lines: string[] = []
  if (isApiError(error)) {
    lines.push(`status: ${error.status}`, `code: ${error.code}`)
    if (error.requestId) lines.push(`request id: ${error.requestId}`)
  }
  lines.push(`message: ${error instanceof Error ? error.message : String(error)}`)
  lines.push(`url: ${window.location.href}`, `time: ${new Date().toISOString()}`)
  if (error instanceof Error && error.stack) lines.push('', error.stack.split('\n').slice(0, 8).join('\n'))
  return lines.join('\n')
}

/** Friendly failure panel with collapsible technical details; used by the router and the top-level boundary. */
export function ErrorPanel({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useTranslation()
  const requestId = isApiError(error) ? error.requestId : undefined
  const report = errorReport(error)
  const d = describeError(t, error)
  return (
    <div role="alert" className="mx-auto my-10 max-w-xl rounded-md border border-border bg-card p-5">
      <div className="flex items-start gap-2.5">
        <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
        <div className="min-w-0 space-y-2">
          <p className="text-sm font-semibold tracking-tight text-foreground">
            {isApiError(error) ? d.title : t('resilience.errorTitle')}
          </p>
          <p className="text-body text-muted-foreground">
            {isApiError(error) ? d.body : t('resilience.errorBody')}
          </p>
          <details className="text-body">
            <summary className="cursor-pointer text-muted-foreground">{t('resilience.details')}</summary>
            {requestId && (
              <p className="mt-2">
                {t('resilience.requestId')}: <code data-testid="request-id">{requestId}</code>
              </p>
            )}
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-muted p-2 text-xs">
              {report}
            </pre>
          </details>
          <div className="flex gap-2 pt-1">
            {!d.notFound && (
              <Button size="sm" onClick={onRetry}>
                {t('resilience.retry')}
              </Button>
            )}
            <ErrorNavigation />
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void navigator.clipboard?.writeText(report).then(() => toast(t('resilience.copied')))
              }}
            >
              {t('resilience.copy')}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

/** `defaultErrorComponent` of the router: an error in a route's loader or render. */
export function RouteError({ error, reset }: { error: unknown; reset: () => void }) {
  return <ErrorPanel error={error} onRetry={reset} />
}

/** Last line of defence around the whole application. */
export class AppErrorBoundary extends Component<{ children: ReactNode }, { error: unknown }> {
  state: { error: unknown } = { error: null }

  static getDerivedStateFromError(error: unknown) {
    return { error: error ?? new Error('unknown error') }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('render error', error, info.componentStack)
  }

  render() {
    if (this.state.error === null) return this.props.children
    return <ErrorPanel error={this.state.error} onRetry={() => this.setState({ error: null })} />
  }
}

import { AlertCircle, KeyRound } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { methodUrl, useLoginMethods, type LoginMethodId } from './sso'

const LABEL_KEYS: Record<Exclude<LoginMethodId, 'form'>, string> = {
  cas: 'sso.signIn.cas',
  'http-basic': 'sso.signIn.httpBasic',
  'http-header': 'sso.signIn.httpHeader',
  oidc: 'sso.signIn.oidc',
}

/**
 * Entry points of the redirect-based login methods (single sign-on, browser credentials, ...),
 * driven by `GET /auth/methods`. Renders nothing when only the form is enabled.
 */
export function SsoEntry({ next, failed }: { next?: string; failed?: boolean }) {
  const { t } = useTranslation()
  const { data } = useLoginMethods()
  const external = (data?.methods ?? []).filter((m) => m.id !== 'form')

  if (external.length === 0 && !failed) return null

  return (
    <div className="mb-5 space-y-3" data-testid="sso-entry">
      {failed && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-sm border border-destructive/30 bg-destructive-soft p-2.5 text-body text-destructive"
        >
          <AlertCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span className="leading-snug">{t('sso.failed')}</span>
        </div>
      )}
      {external.map((method) => (
        <Button
          key={method.id}
          asChild
          variant={data?.login_method === method.id ? 'default' : 'outline'}
          className="h-9 w-full"
        >
          <a href={methodUrl(method, next)}>
            <KeyRound aria-hidden />
            {t(LABEL_KEYS[method.id as Exclude<LoginMethodId, 'form'>])}
          </a>
        </Button>
      ))}
      {external.length > 0 && (
        <div className="flex items-center gap-3" role="separator" aria-label={t('sso.or')}>
          <span className="h-px flex-1 bg-border" />
          <span className="text-xs text-muted-foreground">{t('sso.or')}</span>
          <span className="h-px flex-1 bg-border" />
        </div>
      )}
    </div>
  )
}

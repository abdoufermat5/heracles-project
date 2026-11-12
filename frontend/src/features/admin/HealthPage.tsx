import {
  CheckCircle2,
  CircleAlert,
  CircleCheck,
  CircleX,
  Info,
  RefreshCw,
  ShieldAlert,
  TriangleAlert,
  Wrench,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { ErrorState } from '@/components/ErrorState'
import { ObjectRefPicker } from '@/components/fields/RefFields'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { PageLayout } from '@/components/patterns'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { useCapabilities, useChecks, useFix } from './hooks'
import type { CheckStatus, HealthCheck } from './types'

const STATUS_STYLE: Record<
  CheckStatus,
  {
    variant: 'success' | 'warning' | 'destructive'
    Icon: typeof CircleCheck
    borderClass: string
    bgClass: string
  }
> = {
  ok: {
    variant: 'success',
    Icon: CircleCheck,
    borderClass: 'border-success/30',
    bgClass: 'bg-success/5',
  },
  warning: {
    variant: 'warning',
    Icon: TriangleAlert,
    borderClass: 'border-warning/30',
    bgClass: 'bg-warning/5',
  },
  error: {
    variant: 'destructive',
    Icon: CircleX,
    borderClass: 'border-destructive/30',
    bgClass: 'bg-destructive/5',
  },
}

function CheckCard({ check, canFix }: { check: HealthCheck; canFix: boolean }) {
  const { t } = useTranslation()
  const fix = useFix()
  const [excluded, setExcluded] = useState<Set<string>>(new Set())
  const [adminDn, setAdminDn] = useState('')
  const { variant, Icon, borderClass } = STATUS_STYLE[check.status]
  const selected = check.dns.filter((d) => !excluded.has(d))
  const needsUser = check.options.includes('dn')
  const canApply =
    canFix &&
    check.fixable &&
    (needsUser ? adminDn !== '' : selected.length > 0 || check.dns.length === 0)
  const showDns = check.dns.length > 0 && !needsUser

  const explanation =
    t(`settingsUI.health.checkExpl.${check.id}`) || check.message
  const howToFix = t(`settingsUI.health.checkFix.${check.id}`)

  const apply = async () => {
    try {
      const out = await fix.mutateAsync({
        id: check.id,
        dns: needsUser ? [] : selected,
        options: needsUser ? { dn: adminDn } : {},
      })
      const failed = Object.keys(out.result.failed).length
      if (failed > 0) {
        toast.warning(t('setup.fixPartial', { fixed: out.result.fixed.length, failed }))
      } else {
        toast.success(t('setup.fixed', { count: out.result.fixed.length }))
      }
      setExcluded(new Set())
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const failures = fix.data ? Object.entries(fix.data.result.failed) : []

  return (
    <li
      className={cn(
        'rounded-md border bg-card p-4 transition-all duration-150',
        check.status !== 'ok' && borderClass,
      )}
      data-check={check.id}
      data-status={check.status}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-body font-semibold tracking-tight text-foreground">
              {t(`setup.check.${check.id}`)}
            </h3>
            <Badge variant={variant} className="gap-1">
              <Icon className="size-3" aria-hidden />
              {t(`setup.status.${check.status}`)}
            </Badge>
          </div>

          {/* Plain explanation */}
          <p className="text-body text-foreground/90">{explanation}</p>
          {check.message && check.message !== explanation && (
            <p className="text-caption text-muted-foreground">{check.message}</p>
          )}
        </div>

        {check.fixable && (
          <Button
            size="sm"
            variant={check.status === 'error' ? 'default' : 'outline'}
            disabled={!canApply || fix.isPending}
            onClick={() => void apply()}
          >
            <Wrench className="size-3.5" />
            {needsUser ? t('setup.makeAdmin') : t('setup.applyFix', { count: selected.length })}
          </Button>
        )}
      </div>

      {/* "How to fix" guidance - warning/error checks only */}
      {howToFix && check.status !== 'ok' && (
        <div className="mt-3 flex items-start gap-2 rounded-sm border bg-muted/40 p-2.5 text-small text-muted-foreground">
          <Info className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
          <div className="space-y-0.5">
            <span className="font-medium text-foreground">
              {check.fixable
                ? t('settingsUI.health.summary.remediation')
                : t('settingsUI.health.summary.resolution')}{' '}
            </span>
            <span>{howToFix}</span>
          </div>
        </div>
      )}

      {needsUser && check.fixable && (
        <div className="mt-3 max-w-sm space-y-1.5">
          <Label htmlFor={`fix-${check.id}-user`}>{t('setup.chooseAdmin')}</Label>
          <ObjectRefPicker
            id={`fix-${check.id}-user`}
            refType="user"
            selected={adminDn ? [adminDn] : []}
            label={adminDn || t('setup.chooseAdminPlaceholder')}
            onPick={setAdminDn}
            disabled={!canFix}
          />
          <p className="text-caption text-muted-foreground">{t('setup.chooseAdminHelp')}</p>
        </div>
      )}

      {showDns && (
        <div className="mt-3 space-y-1.5 border-t pt-3">
          <p className="text-caption font-medium text-muted-foreground">
            {t('setup.affected')} ({selected.length}/{check.dns.length}):
          </p>
          <ul className="space-y-1" aria-label={t('setup.affected')}>
            {check.dns.map((dn, i) => {
              const id = `fix-${check.id}-${i}`
              return (
                <li key={dn} className="flex items-center gap-2">
                  {check.fixable ? (
                    <Checkbox
                      id={id}
                      checked={!excluded.has(dn)}
                      disabled={!canFix}
                      onCheckedChange={(on) =>
                        setExcluded((prev) => {
                          const next = new Set(prev)
                          if (on === true) next.delete(dn)
                          else next.add(dn)
                          return next
                        })
                      }
                    />
                  ) : null}
                  <Label htmlFor={id} className="break-all font-mono text-xs font-normal">
                    {dn}
                  </Label>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {failures.length > 0 && (
        <ul role="alert" className="mt-3 space-y-0.5 text-xs text-destructive">
          {failures.map(([dn, why]) => (
            <li key={dn} className="break-all">
              <span className="font-mono">{dn}</span>: {why}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

export function HealthPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch, isFetching } = useChecks()
  const { data: caps } = useCapabilities()
  const canFix = caps?.config_write === true
  const counts = { ok: 0, warning: 0, error: 0 }
  for (const c of data ?? []) counts[c.status] += 1

  const hasErrors = counts.error > 0
  const hasWarnings = counts.warning > 0

  return (
    <PageLayout
        title={t('setup.title')}
        description={t('setup.description')}
        actions={
          <Button
            variant="outline"
            size="sm"
            disabled={isFetching}
            onClick={() => void refetch()}
          >
            <RefreshCw className={cn('size-3.5', isFetching && 'animate-spin')} />
            {t('setup.rerun')}
          </Button>
        }
      >
      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <div className="space-y-3" aria-busy="true">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <div className="space-y-4">
          {/* Summary Card at the top */}
          <div
            className={cn(
              'rounded-md border p-4 shadow-xs transition-colors',
              hasErrors
                ? 'border-destructive/40 bg-destructive-soft'
                : hasWarnings
                  ? 'border-warning/40 bg-warning-soft'
                  : 'border-success/40 bg-success-soft',
            )}
          >
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                {hasErrors ? (
                  <CircleAlert className="size-6 text-destructive" />
                ) : hasWarnings ? (
                  <ShieldAlert className="size-6 text-warning" />
                ) : (
                  <CheckCircle2 className="size-6 text-success" />
                )}
                <div>
                  <h2 className="text-lead font-semibold text-foreground">
                    {hasErrors
                      ? t('settingsUI.health.summary.hasErrors')
                      : hasWarnings
                        ? t('settingsUI.health.summary.hasWarnings')
                        : t('settingsUI.health.summary.allOk')}
                  </h2>
                  <p className="text-small text-muted-foreground">
                    {hasErrors
                      ? t('settingsUI.health.summary.hasErrorsHelp')
                      : hasWarnings
                        ? t('settingsUI.health.summary.hasWarningsHelp')
                        : t('settingsUI.health.summary.allOkHelp')}
                  </p>
                </div>
              </div>

              {/* Status metrics */}
              <div
                className="flex flex-wrap items-center gap-2"
                aria-live="polite"
              >
                <Badge variant="neutral">
                  {t('settingsUI.health.summary.total')}: {data.length}
                </Badge>
                <Badge variant="success">
                  {t('setup.countOk', { count: counts.ok })}
                </Badge>
                <Badge variant="warning">
                  {t('setup.countWarning', { count: counts.warning })}
                </Badge>
                <Badge variant="destructive">
                  {t('setup.countError', { count: counts.error })}
                </Badge>
              </div>
            </div>

            {!canFix && (
              <p className="mt-3 border-t border-border/40 pt-2 text-caption text-muted-foreground">
                {t('setup.readOnly')}
              </p>
            )}
          </div>

          {/* Checklist */}
          <ul className="space-y-3" aria-label={t('setup.title')}>
            {data.map((c) => (
              <CheckCard key={c.id} check={c} canFix={canFix} />
            ))}
          </ul>
        </div>
      )}
    </PageLayout>
  )
}

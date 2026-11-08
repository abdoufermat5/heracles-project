import { CircleCheck, CircleX, RefreshCw, TriangleAlert, Wrench } from 'lucide-react'
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
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { useCapabilities, useChecks, useFix } from './hooks'
import type { CheckStatus, HealthCheck } from './types'

const STATUS_STYLE: Record<CheckStatus, { variant: 'success' | 'warning' | 'destructive'; Icon: typeof CircleCheck }> = {
  ok: { variant: 'success', Icon: CircleCheck },
  warning: { variant: 'warning', Icon: TriangleAlert },
  error: { variant: 'destructive', Icon: CircleX },
}

function CheckCard({ check, canFix }: { check: HealthCheck; canFix: boolean }) {
  const { t } = useTranslation()
  const fix = useFix()
  const [excluded, setExcluded] = useState<Set<string>>(new Set())
  const [adminDn, setAdminDn] = useState('')
  const { variant, Icon } = STATUS_STYLE[check.status]
  const selected = check.dns.filter((d) => !excluded.has(d))
  const needsUser = check.options.includes('dn')
  const canApply = canFix && check.fixable && (needsUser ? adminDn !== '' : selected.length > 0 || check.dns.length === 0)
  const showDns = check.dns.length > 0 && !needsUser

  const apply = async () => {
    try {
      const out = await fix.mutateAsync({
        id: check.id,
        dns: needsUser ? [] : selected,
        options: needsUser ? { dn: adminDn } : {},
      })
      const failed = Object.keys(out.result.failed).length
      if (failed > 0) toast.warning(t('setup.fixPartial', { fixed: out.result.fixed.length, failed }))
      else toast.success(t('setup.fixed', { count: out.result.fixed.length }))
      setExcluded(new Set())
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const failures = fix.data ? Object.entries(fix.data.result.failed) : []

  return (
    <li className="rounded-md border bg-card p-4" data-check={check.id} data-status={check.status}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold tracking-tight">{t(`setup.check.${check.id}`, { defaultValue: check.id })}</h2>
            <Badge variant={variant} className="gap-1">
              <Icon className="size-3" aria-hidden />
              {t(`setup.status.${check.status}`)}
            </Badge>
          </div>
          <p className="text-body text-muted-foreground">{check.message}</p>
        </div>
        {check.fixable && (
          <Button size="sm" variant="outline" disabled={!canApply || fix.isPending} onClick={() => void apply()}>
            <Wrench />
            {needsUser ? t('setup.makeAdmin') : t('setup.applyFix', { count: selected.length })}
          </Button>
        )}
      </div>

      {needsUser && check.fixable && (
        <div className="mt-3 max-w-sm space-y-1">
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
        <ul className="mt-3 space-y-1" aria-label={t('setup.affected')}>
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

  return (
    <div>
      <PageHeader
        title={t('setup.title')}
        description={t('setup.description')}
        actions={
          <Button variant="outline" size="sm" disabled={isFetching} onClick={() => void refetch()}>
            <RefreshCw className={isFetching ? 'animate-spin' : undefined} />
            {t('setup.rerun')}
          </Button>
        }
      />
      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <div className="space-y-2" aria-busy="true">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <div className="space-y-3">
          <p className="flex flex-wrap items-center gap-2 text-body text-muted-foreground" aria-live="polite">
            <Badge variant="success">{t('setup.countOk', { count: counts.ok })}</Badge>
            <Badge variant="warning">{t('setup.countWarning', { count: counts.warning })}</Badge>
            <Badge variant="destructive">{t('setup.countError', { count: counts.error })}</Badge>
            {!canFix && <span>{t('setup.readOnly')}</span>}
          </p>
          <ul className="space-y-3">
            {data.map((c) => (
              <CheckCard key={c.id} check={c} canFix={canFix} />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

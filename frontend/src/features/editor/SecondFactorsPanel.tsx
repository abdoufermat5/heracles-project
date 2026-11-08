import { KeyRound, ShieldOff, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/ErrorState'
import { useSecondFactorMutations, useSecondFactors, type SecurityKeyInfo } from './api'

interface Props {
  dn: string
}

/**
 * Administrator view of a user's second factors, with a confirmed reset.
 *
 * Not a <form>: this panel renders inside the editor's own form.
 */
export function SecondFactorsPanel({ dn }: Props) {
  const { t } = useTranslation()
  const factors = useSecondFactors(dn)
  const { reset, removeKey } = useSecondFactorMutations(dn)
  const [confirmReset, setConfirmReset] = useState(false)
  const [keyToRemove, setKeyToRemove] = useState<SecurityKeyInfo | null>(null)

  const fail = (e: unknown) => toast.error(isApiError(e) ? e.message : t('secondFactors.failed'))

  const doReset = async () => {
    setConfirmReset(false)
    try {
      await reset.mutateAsync()
      toast.success(t('secondFactors.resetDone'))
    } catch (e) {
      fail(e)
    }
  }

  const doRemoveKey = async () => {
    const key = keyToRemove
    setKeyToRemove(null)
    if (!key) return
    try {
      await removeKey.mutateAsync(key.id)
      toast.success(t('secondFactors.keyRemoved'))
    } catch (e) {
      fail(e)
    }
  }

  const data = factors.data
  const registered = data ? data.totp || data.security_keys.length > 0 || data.recovery_codes > 0 : false
  const canReset = data?.can_reset ?? false

  return (
    <section aria-labelledby="second-factors-title" className="rounded-md border bg-card">
      <div className="border-b px-4 py-3">
        <h2 id="second-factors-title" className="text-[13px] font-semibold text-foreground">
          {t('secondFactors.title')}
        </h2>
        <p className="text-xs text-muted-foreground">{t('secondFactors.help')}</p>
      </div>

      {factors.isError ? (
        <div className="p-4">
          <ErrorState error={factors.error} onRetry={() => void factors.refetch()} />
        </div>
      ) : !data ? (
        <div className="space-y-2 p-4" aria-busy="true" aria-label={t('common.loading')}>
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-2/3" />
        </div>
      ) : (
        <>
          <dl className="divide-y text-[13px]">
            <div className="flex items-center justify-between gap-4 px-4 py-2.5">
              <dt className="text-muted-foreground">{t('secondFactors.totp')}</dt>
              <dd className="text-foreground">
                {data.totp ? t('secondFactors.totpOn') : t('secondFactors.totpOff')}
              </dd>
            </div>
            <div className="px-4 py-2.5">
              <dt className="text-muted-foreground">{t('secondFactors.keys')}</dt>
              <dd className="mt-1.5">
                {data.security_keys.length === 0 ? (
                  <span className="text-foreground">{t('secondFactors.noKeys')}</span>
                ) : (
                  <ul aria-label={t('secondFactors.keys')} className="space-y-1">
                    {data.security_keys.map((k) => {
                      const name = k.label || t('secondFactors.unnamedKey')
                      return (
                        <li key={k.id} className="flex items-center gap-2">
                          <KeyRound className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                          <span className="min-w-0 flex-1 truncate text-foreground">{name}</span>
                          {canReset && (
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon-xs"
                              disabled={removeKey.isPending}
                              onClick={() => setKeyToRemove(k)}
                              aria-label={t('secondFactors.removeKey', { name })}
                              className="text-destructive hover:bg-destructive-soft hover:text-destructive"
                            >
                              <Trash2 aria-hidden />
                            </Button>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4 px-4 py-2.5">
              <dt className="text-muted-foreground">{t('secondFactors.recoveryCodes')}</dt>
              <dd className="text-foreground">
                {t('secondFactors.recoveryCount', { count: data.recovery_codes })}
              </dd>
            </div>
          </dl>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3">
            <p className="text-xs text-muted-foreground">
              {!canReset
                ? t('secondFactors.viewOnly')
                : registered
                  ? null
                  : t('secondFactors.none')}
            </p>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={!canReset || !registered || reset.isPending}
              onClick={() => setConfirmReset(true)}
            >
              <ShieldOff aria-hidden />
              {t('secondFactors.reset')}
            </Button>
          </div>
        </>
      )}

      <AlertDialog open={confirmReset} onOpenChange={setConfirmReset}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px] font-semibold">
              {t('secondFactors.resetTitle')}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[13px] text-muted-foreground">
              {t('secondFactors.resetBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void doReset()}>
              {t('secondFactors.resetConfirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={keyToRemove !== null} onOpenChange={(o) => !o && setKeyToRemove(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px] font-semibold">
              {t('secondFactors.removeKeyTitle')}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[13px] text-muted-foreground">
              {t('secondFactors.removeKeyBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void doRemoveKey()}>
              {t('secondFactors.removeKeyConfirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

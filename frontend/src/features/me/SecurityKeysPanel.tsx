import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Loader2, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import { qk } from '@/api/hooks'
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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { createCredential, WebAuthnClientError, webauthnSupported } from '@/lib/webauthn'
import { ReauthDialog } from './ReauthDialog'

const PANEL_HEADER = 'flex h-10 flex-row items-center justify-between border-b px-4 py-0'

/** Self-service management of the user's WebAuthn security keys. */
export function SecurityKeysPanel() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const supported = webauthnSupported()
  const [label, setLabel] = useState('')
  const [error, setError] = useState<string | null>(null)
  /** Action to retry once the password is confirmed (the server asked for step-up). */
  const [retry, setRetry] = useState<(() => void) | null>(null)
  /** Key whose removal would turn the second factor off, awaiting confirmation. */
  const [lastKey, setLastKey] = useState<string | null>(null)

  const needsReauth = (e: unknown) => isApiError(e) && e.code === 'reauth_required'

  const keys = useQuery({ queryKey: qk.securityKeys, queryFn: api.listSecurityKeys })

  const add = useMutation({
    mutationFn: async (name: string) => {
      const { options } = await api.securityKeyOptions()
      const credential = await createCredential(options)
      return api.registerSecurityKey({ label: name, credential })
    },
    onSuccess: async () => {
      setLabel('')
      setError(null)
      await qc.invalidateQueries({ queryKey: qk.securityKeys })
      await qc.invalidateQueries({ queryKey: qk.totp })
    },
    onError: (e, name) => {
      if (needsReauth(e)) {
        setRetry(() => () => add.mutate(name))
        return
      }
      if (e instanceof WebAuthnClientError) {
        if (e.reason === 'cancelled') setError(t('security.cancelled'))
        else if (e.reason === 'unsupported') setError(t('security.unsupported'))
        else setError(t('security.failed'))
      } else {
        setError(isApiError(e) ? e.message : t('security.failed'))
      }
    },
  })

  const remove = useMutation({
    mutationFn: (v: { id: string; confirmDisable?: boolean }) =>
      api.deleteSecurityKey(v.id, v.confirmDisable),
    onSuccess: async () => {
      setError(null)
      await qc.invalidateQueries({ queryKey: qk.securityKeys })
      await qc.invalidateQueries({ queryKey: qk.totp })
    },
    onError: (e, v) => {
      if (needsReauth(e)) setRetry(() => () => remove.mutate(v))
      else if (isApiError(e) && e.code === 'last_second_factor') setLastKey(v.id)
      else setError(isApiError(e) ? e.message : t('security.failed'))
    },
  })

  return (
    <Card className="overflow-hidden lg:col-span-2">
      <CardHeader className={PANEL_HEADER}>
        <CardTitle className="text-[13px] font-semibold">{t('security.title')}</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <p className="px-4 pt-3 text-xs text-muted-foreground">{t('security.help')}</p>

        {error && (
          <p role="alert" className="mx-4 mt-3 rounded-sm border border-destructive/30 bg-destructive-soft p-2.5 text-[13px] text-destructive">
            {error}
          </p>
        )}

        {keys.isPending ? (
          <p className="px-4 py-3 text-[13px] text-muted-foreground">{t('common.loading')}</p>
        ) : keys.data && keys.data.length > 0 ? (
          <ul className="mt-3 divide-y border-t text-[13px]" aria-label={t('security.title')}>
            {keys.data.map((k) => (
              <li key={k.id} className="flex items-center gap-2 px-4 py-2.5">
                <KeyRound className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-foreground">
                  {k.label || t('security.unnamed')}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate({ id: k.id })}
                  aria-label={t('security.remove', { name: k.label || t('security.unnamed') })}
                  className="text-destructive hover:bg-destructive-soft hover:text-destructive"
                >
                  <Trash2 aria-hidden="true" />
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-3 text-[13px] text-muted-foreground">{t('security.none')}</p>
        )}

        <div className="border-t p-4">
          {supported ? (
            <form
              className="flex items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                setError(null)
                add.mutate(label.trim())
              }}
            >
              <Input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                maxLength={64}
                placeholder={t('security.labelPlaceholder')}
                aria-label={t('security.label')}
                className="h-8 max-w-64 text-[13px]"
              />
              <Button type="submit" size="sm" disabled={add.isPending}>
                {add.isPending ? (
                  <Loader2 className="animate-spin" aria-hidden="true" />
                ) : (
                  <KeyRound aria-hidden="true" />
                )}
                {t('security.add')}
              </Button>
            </form>
          ) : (
            <p className="text-[13px] text-muted-foreground">{t('security.unsupported')}</p>
          )}
        </div>
      </CardContent>

      <ReauthDialog
        open={retry !== null}
        onCancel={() => setRetry(null)}
        onConfirmed={() => {
          const again = retry
          setRetry(null)
          again?.()
        }}
      />

      <AlertDialog open={lastKey !== null} onOpenChange={(o) => !o && setLastKey(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px]">{t('security.lastTitle')}</AlertDialogTitle>
            <AlertDialogDescription className="text-[13px]">
              {t('security.lastBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('security.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (lastKey) remove.mutate({ id: lastKey, confirmDisable: true })
                setLastKey(null)
              }}
            >
              {t('security.lastConfirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

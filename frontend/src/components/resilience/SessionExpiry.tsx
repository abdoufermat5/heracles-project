import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { isApiError, setReauthHandler } from '@/api/client'
import { api } from '@/api/endpoints'
import { qk } from '@/api/hooks'
import type { Me } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

/**
 * Signs the user in again, in place, when the session expired under an API call. The
 * failed request is then retried by the client and the page (with its unsaved form
 * state) is never left. A second factor other than a TOTP code falls back to the login page.
 */
export function SessionExpiry() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [identity, setIdentity] = useState<Me | null>(null)
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [needCode, setNeedCode] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const pending = useRef<{ promise: Promise<boolean>; settle: (ok: boolean) => void } | null>(null)

  const finish = useCallback((ok: boolean) => {
    setOpen(false)
    setPassword('')
    setCode('')
    setNeedCode(false)
    setError(null)
    pending.current?.settle(ok)
    pending.current = null
  }, [])

  useEffect(() => {
    setReauthHandler(() => {
      if (pending.current) return pending.current.promise // concurrent 401s share one dialog
      const me = qc.getQueryData<Me>(qk.me)
      if (!me) return Promise.resolve(false)
      setIdentity(me)
      setOpen(true)
      let settle: (ok: boolean) => void = () => undefined
      const promise = new Promise<boolean>((resolve) => {
        settle = resolve
      })
      pending.current = { promise, settle }
      return promise
    })
    return () => setReauthHandler(null)
  }, [qc])

  async function submit() {
    if (!identity) return
    setBusy(true)
    setError(null)
    try {
      if (needCode) {
        await api.secondFactor({ method: 'totp', code })
        finish(true)
      } else {
        const r = await api.login({
          directory: identity.directory,
          username: identity.uid,
          password,
        })
        if (r.status === 'ok') finish(true)
        else if (r.methods?.includes('totp')) setNeedCode(true)
        else finish(false)
      }
    } catch (e) {
      setError(isApiError(e) ? e.message : t('resilience.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && finish(false)}>
      <DialogContent>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          <DialogHeader>
            <DialogTitle className="text-lead">{t('resilience.expiredTitle')}</DialogTitle>
            <DialogDescription className="text-body">{t('resilience.expiredBody')}</DialogDescription>
          </DialogHeader>
          <p className="text-body text-muted-foreground">
            {t('resilience.account')}: <code>{identity?.uid}</code>
          </p>
          {needCode ? (
            <Input
              key="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              value={code}
              onChange={(e) => setCode(e.target.value)}
              aria-label={t('resilience.code')}
              className="h-8 text-body"
            />
          ) : (
            <Input
              key="password"
              type="password"
              autoComplete="current-password"
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-label={t('resilience.password')}
              className="h-8 text-body"
            />
          )}
          {error && (
            <p role="alert" className="text-body text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" size="sm" onClick={() => finish(false)}>
              {t('resilience.cancel')}
            </Button>
            <Button type="submit" size="sm" disabled={busy || !(needCode ? code : password)}>
              {t('resilience.signIn')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

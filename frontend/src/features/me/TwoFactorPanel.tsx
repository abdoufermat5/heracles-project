import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Download, Loader2, ShieldCheck, Smartphone } from 'lucide-react'
import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import { qk } from '@/api/hooks'
import type { TotpEnrolment } from '@/api/types'
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
import { ReauthDialog } from './ReauthDialog'

const PANEL_HEADER = 'flex h-10 flex-row items-center justify-between border-b px-4 py-0'

/** Self-service setup of the authenticator app (TOTP) and of the recovery codes. */
export function TwoFactorPanel() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  /** Action to retry once the password is confirmed (the server asked for step-up). */
  const [retry, setRetry] = useState<(() => void) | null>(null)
  /** Secret being enrolled: shown with its QR code until a valid code confirms it. */
  const [setup, setSetup] = useState<TotpEnrolment | null>(null)
  const [code, setCode] = useState('')
  const [codeError, setCodeError] = useState<string | null>(null)
  /** Recovery codes in clear: only available right after generation. */
  const [codes, setCodes] = useState<string[] | null>(null)
  const [copied, setCopied] = useState(false)
  const [confirmLast, setConfirmLast] = useState(false)

  const needsReauth = (e: unknown) => isApiError(e) && e.code === 'reauth_required'
  const status = useQuery({ queryKey: qk.totp, queryFn: api.totpStatus })
  const refresh = () => qc.invalidateQueries({ queryKey: qk.totp })

  const begin = useMutation({
    mutationFn: api.totpBegin,
    onSuccess: (r) => {
      setError(null)
      setCode('')
      setCodeError(null)
      setSetup(r)
    },
    onError: (e) => {
      if (needsReauth(e)) setRetry(() => () => begin.mutate())
      else setError(isApiError(e) ? e.message : t('twofactor.failed'))
    },
  })

  const confirm = useMutation({
    mutationFn: (value: string) => api.totpConfirm(value),
    onSuccess: async () => {
      setSetup(null)
      setCode('')
      setCodeError(null)
      await refresh()
    },
    onError: (e, value) => {
      if (needsReauth(e)) setRetry(() => () => confirm.mutate(value))
      else if (isApiError(e) && e.code === 'validation') setCodeError(e.fields.code ?? e.message)
      else setCodeError(isApiError(e) ? e.message : t('twofactor.failed'))
    },
  })

  const disable = useMutation({
    mutationFn: (confirmDisable: boolean) => api.totpDisable(confirmDisable),
    onSuccess: async () => {
      setError(null)
      await refresh()
    },
    onError: (e, confirmDisable) => {
      if (needsReauth(e)) setRetry(() => () => disable.mutate(confirmDisable))
      else if (isApiError(e) && e.code === 'last_second_factor') setConfirmLast(true)
      else setError(isApiError(e) ? e.message : t('twofactor.failed'))
    },
  })

  const generate = useMutation({
    mutationFn: api.generateRecoveryCodes,
    onSuccess: async (r) => {
      setError(null)
      setCopied(false)
      setCodes(r.codes)
      await refresh()
    },
    onError: (e) => {
      if (needsReauth(e)) setRetry(() => () => generate.mutate())
      else setError(isApiError(e) ? e.message : t('twofactor.failed'))
    },
  })

  const enabled = status.data?.enabled ?? false
  const remaining = status.data?.recovery_codes_remaining ?? 0
  const hasFactor = enabled || (status.data?.security_keys ?? 0) > 0

  const copyCodes = async () => {
    if (!codes) return
    try {
      await navigator.clipboard.writeText(codes.join('\n'))
      setCopied(true)
    } catch {
      setError(t('twofactor.failed'))
    }
  }

  return (
    <Card className="overflow-hidden lg:col-span-2">
      <CardHeader className={PANEL_HEADER}>
        <CardTitle className="text-body font-semibold">{t('twofactor.title')}</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <p className="px-4 pt-3 text-caption text-muted-foreground">{t('twofactor.help')}</p>

        {error && (
          <p role="alert" className="mx-4 mt-3 rounded-sm border border-destructive/30 bg-destructive-soft p-2.5 text-body text-destructive">
            {error}
          </p>
        )}

        {status.isPending ? (
          <p className="px-4 py-3 text-body text-muted-foreground">{t('common.loading')}</p>
        ) : (
          <>
            <section aria-label={t('twofactor.appTitle')} className="mt-3 border-t p-4">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-2 text-body">
                <Smartphone className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className="font-medium text-foreground">{t('twofactor.appTitle')}</span>
                <span className="min-w-32 flex-1 text-muted-foreground">
                  {enabled ? t('twofactor.appOn') : t('twofactor.appOff')}
                </span>
                {enabled && !setup && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={disable.isPending}
                    onClick={() => disable.mutate(false)}
                    className="text-destructive hover:bg-destructive-soft hover:text-destructive"
                  >
                    {t('twofactor.disable')}
                  </Button>
                )}
                {!enabled && !setup && (
                  <Button type="button" size="sm" disabled={begin.isPending} onClick={() => begin.mutate()}>
                    {begin.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
                    {t('twofactor.enable')}
                  </Button>
                )}
              </div>

              {setup && (
                <form
                  className="mt-4 grid gap-3"
                  onSubmit={(e) => {
                    e.preventDefault()
                    setCodeError(null)
                    confirm.mutate(code.trim())
                  }}
                >
                  <p className="text-body text-muted-foreground">{t('twofactor.scan')}</p>
                  <QrImage value={setup.uri} alt={t('twofactor.qrAlt')} />
                  <div className="grid gap-1 text-body">
                    <span className="text-caption text-muted-foreground">{t('twofactor.secret')}</span>
                    <code data-testid="totp-secret" className="w-fit select-all rounded-sm bg-muted px-2 py-1 font-mono text-xs tracking-wider">
                      {setup.secret}
                    </code>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Input
                      value={code}
                      onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={6}
                      aria-label={t('twofactor.code')}
                      aria-invalid={codeError !== null}
                      className="h-8 w-32 text-center font-mono text-body tracking-widest"
                    />
                    <Button type="submit" size="sm" disabled={code.length !== 6 || confirm.isPending}>
                      {confirm.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
                      {t('twofactor.verify')}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setSetup(null)
                        setCodeError(null)
                      }}
                    >
                      {t('twofactor.cancel')}
                    </Button>
                  </div>
                  {codeError && (
                    <p role="alert" className="text-body text-destructive">
                      {codeError}
                    </p>
                  )}
                </form>
              )}
            </section>

            <section aria-label={t('twofactor.recoveryTitle')} className="border-t p-4">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-2 text-body">
                <ShieldCheck className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className="font-medium text-foreground">{t('twofactor.recoveryTitle')}</span>
                <span className="min-w-32 flex-1 text-muted-foreground">
                  {remaining > 0 ? t('twofactor.recoveryRemaining', { count: remaining }) : t('twofactor.recoveryNone')}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!hasFactor || generate.isPending}
                  onClick={() => generate.mutate()}
                >
                  {generate.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
                  {remaining > 0 || codes ? t('twofactor.regenerate') : t('twofactor.generate')}
                </Button>
              </div>
              <p className="mt-2 text-caption text-muted-foreground">
                {hasFactor ? t('twofactor.recoveryHelp') : t('twofactor.needsFactor')}
              </p>

              {codes && (
                <div className="mt-3 grid gap-3">
                  <p className="text-body text-foreground">{t('twofactor.saveNow')}</p>
                  <ul
                    aria-label={t('twofactor.recoveryTitle')}
                    className="grid w-fit grid-cols-2 gap-x-6 gap-y-1 rounded-sm border bg-muted/40 p-3 font-mono text-body"
                  >
                    {codes.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button type="button" variant="outline" size="sm" onClick={() => void copyCodes()}>
                      {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                      {copied ? t('twofactor.copied') : t('twofactor.copy')}
                    </Button>
                    <Button type="button" variant="outline" size="sm" onClick={() => downloadCodes(codes)}>
                      <Download aria-hidden="true" />
                      {t('twofactor.download')}
                    </Button>
                    <Button type="button" size="sm" onClick={() => setCodes(null)}>
                      {t('twofactor.done')}
                    </Button>
                  </div>
                </div>
              )}
            </section>
          </>
        )}
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

      <AlertDialog open={confirmLast} onOpenChange={setConfirmLast}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lead">{t('twofactor.lastTitle')}</AlertDialogTitle>
            <AlertDialogDescription className="text-body">{t('twofactor.lastBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('twofactor.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                setConfirmLast(false)
                disable.mutate(true)
              }}
            >
              {t('twofactor.lastConfirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

/** QR code of ``value``, rendered locally (the secret never leaves the browser). */
function QrImage({ value, alt }: { value: string; alt: string }) {
  const [src, setSrc] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    QRCode.toString(value, { type: 'svg', margin: 1, errorCorrectionLevel: 'M' })
      .then((svg) => {
        if (live) setSrc(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`)
      })
      .catch(() => {
        if (live) setSrc(null)
      })
    return () => {
      live = false
    }
  }, [value])
  if (!src) return null
  // White backdrop: authenticator apps need a light quiet zone even in dark mode.
  return <img src={src} alt={alt} className="size-44 rounded-sm border bg-white" />
}

function downloadCodes(codes: string[]): void {
  const url = URL.createObjectURL(new Blob([codes.join('\n') + '\n'], { type: 'text/plain' }))
  const a = document.createElement('a')
  a.href = url
  a.download = 'recovery-codes.txt'
  a.click()
  URL.revokeObjectURL(url)
}

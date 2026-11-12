import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
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

/** Asks for the current password, then lets the caller retry the refused action. */
export function ReauthDialog({
  open,
  onCancel,
  onConfirmed,
  body,
}: {
  open: boolean
  onCancel: () => void
  onConfirmed: () => void
  /** Explains what the confirmation is for (defaults to the two-factor wording). */
  body?: string
}) {
  const { t } = useTranslation()
  const [useCode, setUseCode] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const confirm = useMutation({
    mutationFn: (value: string) =>
      api.reauth(useCode ? { method: 'totp', code: value.trim() } : { password: value }),
    onSuccess: () => {
      setPassword('')
      setError(null)
      onConfirmed()
    },
    onError: (e) => setError(isApiError(e) ? e.message : t('security.failed')),
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          setPassword('')
          setError(null)
          onCancel()
        }
      }}
    >
      <DialogContent>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            confirm.mutate(password)
          }}
        >
          <DialogHeader>
            <DialogTitle className="text-lead">{t('security.reauthTitle')}</DialogTitle>
            <DialogDescription className="text-body">
              {body ?? t('security.reauthBody')}
            </DialogDescription>
          </DialogHeader>
          <Input
            type={useCode ? 'text' : 'password'}
            autoComplete={useCode ? 'one-time-code' : 'current-password'}
            inputMode={useCode ? 'numeric' : undefined}
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-label={useCode ? t('reauth.code') : t('security.password')}
            className="h-8 text-body"
          />
          <button
            type="button"
            className="justify-self-start text-body text-primary underline-offset-4 hover:underline"
            onClick={() => {
              setUseCode((v) => !v)
              setPassword('')
              setError(null)
            }}
          >
            {useCode ? t('reauth.usePassword') : t('reauth.useCode')}
          </button>
          {error && (
            <p role="alert" className="text-body text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" size="sm" onClick={onCancel}>
              {t('security.cancel')}
            </Button>
            <Button type="submit" size="sm" disabled={!password || confirm.isPending}>
              {t('security.confirm')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

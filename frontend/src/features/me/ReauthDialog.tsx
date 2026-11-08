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
}: {
  open: boolean
  onCancel: () => void
  onConfirmed: () => void
}) {
  const { t } = useTranslation()
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const confirm = useMutation({
    mutationFn: (pw: string) => api.reauth(pw),
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
            <DialogDescription className="text-body">{t('security.reauthBody')}</DialogDescription>
          </DialogHeader>
          <Input
            type="password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-label={t('security.password')}
            className="h-8 text-body"
          />
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

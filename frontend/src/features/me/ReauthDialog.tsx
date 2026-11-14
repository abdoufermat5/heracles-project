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
import { BlockedHint, blockedProps, FieldError, useLiveForm, type FieldErrors } from '@/lib/liveForm'
import { reauthErrors, reauthMethod } from './validation'

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
  const [refused, setRefused] = useState<FieldErrors | undefined>(undefined)
  const form = useLiveForm(
    'reauth',
    { value: password },
    (v) => reauthErrors(v, useCode),
    refused,
  )
  const confirm = useMutation({
    mutationFn: (value: string) =>
      api.reauth(
        useCode
          ? { method: reauthMethod(value), code: value.trim() }
          : { password: value },
      ),
    onSuccess: () => {
      setPassword('')
      setRefused(undefined)
      form.reset()
      onConfirmed()
    },
    // a wrong password or code is shown under the field it concerns
    onError: (e) => setRefused({ value: isApiError(e) ? e.message : t('security.failed') }),
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          setPassword('')
          setRefused(undefined)
          form.reset()
          onCancel()
        }
      }}
    >
      <DialogContent>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (form.attempt()) confirm.mutate(useCode ? password.trim() : password)
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
            {...form.field('value')}
            className="h-8 text-body"
          />
          <FieldError formId="reauth" name="value" form={form} className="text-body" />
          <button
            type="button"
            className="justify-self-start text-body text-primary underline-offset-4 hover:underline"
            onClick={() => {
              setUseCode((v) => !v)
              setPassword('')
              setRefused(undefined)
              form.reset()
            }}
          >
            {useCode ? t('reauth.usePassword') : t('reauth.useCode')}
          </button>
          <BlockedHint form={form} />
          <DialogFooter>
            <Button type="button" variant="outline" size="sm" onClick={onCancel}>
              {t('security.cancel')}
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={!password || confirm.isPending}
              {...blockedProps(form)}
            >
              {t('security.confirm')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

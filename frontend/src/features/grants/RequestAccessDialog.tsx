import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
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
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { accessApi } from './api'

const SELECT =
  'h-9 w-full rounded-md border border-input bg-card px-2.5 text-body outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40'

type Field = 'target' | 'reason' | 'until'

/** Ask to join a group or role: what, why, and until when. */
export function RequestAccessDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const options = useQuery({
    queryKey: ['access', 'requestable'],
    queryFn: ({ signal }) => accessApi.requestable(signal),
    enabled: open,
  })
  const [target, setTarget] = useState('')
  const [reason, setReason] = useState('')
  const [until, setUntil] = useState('')
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({})
  const maxDays = options.data?.max_days ?? 0
  // the day the dialog opened bounds the date picker (stable across renders)
  const [opened] = useState(() => Date.now())
  const today = new Date(opened).toISOString().slice(0, 10)
  const latest = maxDays ? new Date(opened + maxDays * 86_400_000).toISOString().slice(0, 10) : undefined

  const submit = useMutation({
    mutationFn: () => accessApi.createRequest({ target, reason: reason.trim(), until: until || null }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['access'] })
      toast.success(t('grants.request.sent'))
      onOpenChange(false)
    },
    onError: (e) => {
      if (isApiError(e) && Object.keys(e.fields).length) setErrors(e.fields as Partial<Record<Field, string>>)
      else toast.error(isApiError(e) ? e.message : t('grants.request.failed'))
    },
  })

  function validate(): boolean {
    const found: Partial<Record<Field, string>> = {}
    if (!target) found.target = t('grants.request.pickTarget')
    if (!reason.trim()) found.reason = t('grants.request.needReason')
    if (maxDays && !until) found.until = t('grants.request.needUntil', { days: maxDays })
    setErrors(found)
    return Object.keys(found).length === 0
  }

  const items = options.data?.items ?? []
  const fieldError = (f: Field) =>
    errors[f] ? (
      <p id={`req-${f}-error`} role="alert" className="text-small text-destructive">
        {errors[f]}
      </p>
    ) : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('grants.request.title')}</DialogTitle>
          <DialogDescription>{t('grants.request.description')}</DialogDescription>
        </DialogHeader>
        {options.isSuccess && items.length === 0 ? (
          <p className="text-small text-muted-foreground">{t('grants.request.nothing')}</p>
        ) : (
          <form
            id="request-access-form"
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (validate()) submit.mutate()
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="req-target">{t('grants.request.target')}</Label>
              <select
                id="req-target"
                className={SELECT}
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                aria-invalid={errors.target ? true : undefined}
                aria-describedby={errors.target ? 'req-target-error' : undefined}
              >
                <option value="">{t('grants.request.choose')}</option>
                {items.map((i) => (
                  <option key={i.dn} value={i.dn}>
                    {i.renews
                      ? t('grants.request.renewOption', { label: i.label, day: i.renews.slice(0, 10) })
                      : i.description
                        ? `${i.label} — ${i.description}`
                        : i.label}
                  </option>
                ))}
              </select>
              {fieldError('target')}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="req-reason">{t('grants.request.reason')}</Label>
              <Textarea
                id="req-reason"
                rows={3}
                maxLength={1000}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                aria-invalid={errors.reason ? true : undefined}
                aria-describedby={errors.reason ? 'req-reason-error' : undefined}
              />
              {fieldError('reason')}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="req-until">{t('grants.request.until')}</Label>
              <Input
                id="req-until"
                type="date"
                min={today}
                max={latest}
                value={until}
                onChange={(e) => setUntil(e.target.value)}
                aria-invalid={errors.until ? true : undefined}
                aria-describedby={errors.until ? 'req-until-error' : 'req-until-hint'}
              />
              {fieldError('until') ?? (
                <p id="req-until-hint" className="text-small text-muted-foreground">
                  {maxDays ? t('grants.request.untilHintMax', { days: maxDays }) : t('grants.request.untilHint')}
                </p>
              )}
            </div>
          </form>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t('grants.endDate.cancel')}
          </Button>
          {items.length ? (
            <Button type="submit" form="request-access-form" disabled={submit.isPending}>
              {t('grants.request.submit')}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

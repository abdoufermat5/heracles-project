import { useMutation, useQueryClient } from '@tanstack/react-query'
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
import { accessApi } from './api'
import { endDay } from './hooks'
import type { Grant } from './types'

/** Give one membership an end date, change it, or make it permanent again. */
export function EndDateDialog({
  open,
  onOpenChange,
  holder,
  kind,
  member,
  memberName,
  current,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  holder: string
  kind: string
  member: string
  memberName: string
  current: Grant | undefined
}) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [day, setDay] = useState(current ? endDay(current.until) : '')
  const [error, setError] = useState<string | null>(null)
  const today = new Date().toISOString().slice(0, 10)

  const save = useMutation({
    mutationFn: (until: string | null) => accessApi.setEndDate({ holder, kind, member, until }),
    onSuccess: (_r, until) => {
      void qc.invalidateQueries({ queryKey: ['access'] })
      toast.success(until ? t('grants.endDate.saved', { day: until }) : t('grants.endDate.cleared'))
      onOpenChange(false)
    },
    onError: (e) => setError(isApiError(e) ? (e.fields.until ?? e.fields.member ?? e.message) : t('grants.endDate.failed')),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('grants.endDate.title', { name: memberName })}</DialogTitle>
          <DialogDescription>{t('grants.endDate.description')}</DialogDescription>
        </DialogHeader>
        <form
          id="end-date-form"
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault()
            setError(null)
            if (!day) {
              setError(t('grants.endDate.required'))
              return
            }
            save.mutate(day)
          }}
        >
          <Label htmlFor="end-date">{t('grants.endDate.label')}</Label>
          <Input
            id="end-date"
            type="date"
            min={today}
            value={day}
            onChange={(e) => setDay(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? 'end-date-error' : undefined}
          />
          {error ? (
            <p id="end-date-error" role="alert" className="text-small text-destructive">
              {error}
            </p>
          ) : (
            <p className="text-small text-muted-foreground">{t('grants.endDate.hint')}</p>
          )}
        </form>
        <DialogFooter>
          {current ? (
            <Button type="button" variant="ghost" disabled={save.isPending} onClick={() => save.mutate(null)}>
              {t('grants.endDate.clear')}
            </Button>
          ) : null}
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t('grants.endDate.cancel')}
          </Button>
          <Button type="submit" form="end-date-form" disabled={save.isPending}>
            {t('grants.endDate.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

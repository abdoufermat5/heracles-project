import { useMutation, useQueryClient } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { SectionCard } from '@/components/patterns/SectionCard'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { rdnValue } from '@/lib/objects'
import { accessApi } from './api'
import { endDay, useApprovals, useMyEndDates, useMyRequests } from './hooks'
import { RequestAccessDialog } from './RequestAccessDialog'
import type { AccessRequest } from './types'

function day(seconds: number): string {
  return new Date(seconds * 1000).toISOString().slice(0, 10)
}

/** The signed-in person's requests, and a way to ask for more access (portal and Me page). */
export function MyRequestsSection() {
  const { t } = useTranslation()
  const available = useMyEndDates().enabled
  const mine = useMyRequests(available)
  const qc = useQueryClient()
  const [asking, setAsking] = useState(false)
  const cancel = useMutation({
    mutationFn: (id: string) => accessApi.cancel(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['access'] }),
    onError: (e) => toast.error(isApiError(e) ? e.message : t('grants.request.failed')),
  })
  if (!available) return null
  const items = mine.data?.items ?? []
  return (
    <SectionCard
      id="portal-access-requests"
      title={t('grants.mine.title')}
      description={t('grants.mine.description')}
      actions={
        <Button type="button" size="sm" variant="outline" onClick={() => setAsking(true)}>
          <KeyRound className="size-3.5" aria-hidden />
          {t('grants.request.open')}
        </Button>
      }
    >
      {items.length === 0 ? (
        <p className="text-small text-muted-foreground">{t('grants.mine.empty')}</p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {items.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
              <div className="min-w-0">
                <p className="text-body font-medium text-foreground">{r.target.label}</p>
                <p className="text-small text-muted-foreground">
                  {t(`grants.status.${r.status}`)} · {day(r.created_at)}
                  {r.until ? ` · ${t('grants.until', { day: endDay(r.until) })}` : ''}
                </p>
                {r.comment ? <p className="text-small text-muted-foreground">“{r.comment}”</p> : null}
              </div>
              {r.status === 'pending' ? (
                <Button type="button" size="sm" variant="ghost" disabled={cancel.isPending} onClick={() => cancel.mutate(r.id)}>
                  {t('grants.mine.cancel')}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {asking ? <RequestAccessDialog open onOpenChange={setAsking} /> : null}
    </SectionCard>
  )
}

/** Approve or reject one request, with a comment (required to reject). */
function DecisionDialog({
  request,
  decision,
  onClose,
}: {
  request: AccessRequest
  decision: 'approve' | 'reject'
  onClose: () => void
}) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [comment, setComment] = useState('')
  const [error, setError] = useState<string | null>(null)
  const decide = useMutation({
    mutationFn: () =>
      decision === 'approve' ? accessApi.approve(request.id, comment) : accessApi.reject(request.id, comment),
    onSuccess: ({ request: done }) => {
      void qc.invalidateQueries({ queryKey: ['access'] })
      if (done.status === 'failed') toast.error(t('grants.approvals.applyFailed', { error: done.error }))
      else toast.success(t(`grants.approvals.done.${done.status}`))
      onClose()
    },
    onError: (e) => setError(isApiError(e) ? (e.fields.comment ?? e.message) : t('grants.request.failed')),
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t(decision === 'approve' ? 'grants.approvals.approveTitle' : 'grants.approvals.rejectTitle', {
              member: rdnValue(request.member),
              target: request.target.label,
            })}
          </DialogTitle>
          <DialogDescription>{request.reason}</DialogDescription>
        </DialogHeader>
        <form
          id="decision-form"
          className="space-y-1.5"
          onSubmit={(e) => {
            e.preventDefault()
            if (decision === 'reject' && !comment.trim()) {
              setError(t('grants.approvals.needComment'))
              return
            }
            decide.mutate()
          }}
        >
          <Label htmlFor="decision-comment">
            {t(decision === 'reject' ? 'grants.approvals.commentRequired' : 'grants.approvals.comment')}
          </Label>
          <Textarea
            id="decision-comment"
            rows={3}
            maxLength={1000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? 'decision-error' : undefined}
          />
          {error ? (
            <p id="decision-error" role="alert" className="text-small text-destructive">
              {error}
            </p>
          ) : null}
        </form>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t('grants.endDate.cancel')}
          </Button>
          <Button
            type="submit"
            form="decision-form"
            variant={decision === 'reject' ? 'destructive' : 'default'}
            disabled={decide.isPending}
          >
            {t(decision === 'approve' ? 'grants.approvals.approve' : 'grants.approvals.reject')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** The list of requests waiting for the caller; `hideWhenEmpty` for the portal. */
export function ApprovalsList({
  hideWhenEmpty = false,
  showDn = true,
}: {
  hideWhenEmpty?: boolean
  /** The member DN under the name (console; the portal keeps plain language). */
  showDn?: boolean
}) {
  const { t } = useTranslation()
  const approvals = useApprovals()
  const [deciding, setDeciding] = useState<{ request: AccessRequest; decision: 'approve' | 'reject' } | null>(null)
  if (!approvals.isSuccess) return null
  const items = approvals.data.items
  if (hideWhenEmpty && items.length === 0) return null
  return (
    <SectionCard id="access-approvals" title={t('grants.approvals.title')} description={t('grants.approvals.description')}>
      {items.length === 0 ? (
        <EmptyState icon={<KeyRound className="size-6 text-muted-foreground" aria-hidden />} title={t('grants.approvals.empty')} />
      ) : (
        <ul className="divide-y rounded-lg border">
          {items.map((r) => (
            <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 px-3 py-3">
              <div className="min-w-0 space-y-0.5">
                <p className="text-body text-foreground">
                  {t('grants.approvals.line', { member: rdnValue(r.member), target: r.target.label })}
                </p>
                {showDn ? <p className="font-mono text-caption text-muted-foreground">{r.member}</p> : null}
                <p className="text-small text-muted-foreground">
                  {day(r.created_at)} · {r.until ? t('grants.until', { day: endDay(r.until) }) : t('grants.permanent')}
                </p>
                <p className="text-small text-foreground">“{r.reason}”</p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button type="button" size="sm" variant="outline" onClick={() => setDeciding({ request: r, decision: 'reject' })}>
                  {t('grants.approvals.reject')}
                </Button>
                <Button type="button" size="sm" onClick={() => setDeciding({ request: r, decision: 'approve' })}>
                  {t('grants.approvals.approve')}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {deciding ? (
        <DecisionDialog request={deciding.request} decision={deciding.decision} onClose={() => setDeciding(null)} />
      ) : null}
    </SectionCard>
  )
}

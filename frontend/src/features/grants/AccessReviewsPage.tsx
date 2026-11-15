import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ClipboardCheck, Plus, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { ErrorState } from '@/components/ErrorState'
import { DepartmentPicker, ObjectRefPicker } from '@/components/fields/RefFields'
import { PageLayout } from '@/components/patterns'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { rdnValue } from '@/lib/objects'
import { accessApi } from './api'
import { secondsDay, useCampaigns } from './hooks'
import type { CampaignBody } from './types'

const SELECT =
  'h-9 w-full rounded-md border border-input bg-card px-2.5 text-body outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40'

type Field = 'name' | 'holders' | 'deadline'

function NewCampaignDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [holders, setHolders] = useState<string[]>([])
  const [base, setBase] = useState('')
  const [reviewer, setReviewer] = useState<CampaignBody['reviewer']>('owner')
  const [deadline, setDeadline] = useState('')
  const [fallback, setFallback] = useState<CampaignBody['default']>('keep')
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({})
  const [opened] = useState(() => Date.now())

  const create = useMutation({
    mutationFn: () => accessApi.createCampaign({ name: name.trim(), holders, base, reviewer, deadline, default: fallback }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['access'] })
      toast.success(t('grants.reviews.created'))
      onClose()
    },
    onError: (e) => {
      if (isApiError(e) && Object.keys(e.fields).length) setErrors(e.fields as Partial<Record<Field, string>>)
      else toast.error(isApiError(e) ? e.message : t('grants.reviews.createFailed'))
    },
  })

  function submit() {
    const found: Partial<Record<Field, string>> = {}
    if (!name.trim()) found.name = t('grants.reviews.needName')
    if (!holders.length && !base) found.holders = t('grants.reviews.needScope')
    if (!deadline) found.deadline = t('grants.reviews.needDeadline')
    setErrors(found)
    if (!Object.keys(found).length) create.mutate()
  }

  const err = (f: Field) =>
    errors[f] ? (
      <p id={`campaign-${f}-error`} role="alert" className="text-small text-destructive">
        {errors[f]}
      </p>
    ) : null

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('grants.reviews.newTitle')}</DialogTitle>
          <DialogDescription>{t('grants.reviews.newDescription')}</DialogDescription>
        </DialogHeader>
        <form
          id="campaign-form"
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="campaign-name">{t('grants.reviews.name')}</Label>
            <Input
              id="campaign-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              aria-invalid={errors.name ? true : undefined}
              aria-describedby={errors.name ? 'campaign-name-error' : undefined}
            />
            {err('name')}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="campaign-groups">{t('grants.reviews.groups')}</Label>
            <ObjectRefPicker
              id="campaign-groups"
              refType="group"
              label={t('grants.reviews.addGroup')}
              selected={holders}
              invalid={Boolean(errors.holders)}
              onPick={(dn) => setHolders((h) => (h.includes(dn) ? h : [...h, dn]))}
            />
            {holders.length ? (
              <ul className="flex flex-wrap gap-1.5">
                {holders.map((dn) => (
                  <li key={dn} className="flex items-center gap-1 rounded-md border bg-muted/40 px-2 py-0.5 text-small">
                    <span title={dn}>{rdnValue(dn)}</span>
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-foreground"
                      aria-label={t('grants.reviews.removeGroup', { name: rdnValue(dn) })}
                      onClick={() => setHolders((h) => h.filter((x) => x !== dn))}
                    >
                      <X className="size-3" aria-hidden />
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="campaign-base">{t('grants.reviews.department')}</Label>
            <DepartmentPicker id="campaign-base" value={base || null} onChange={setBase} />
            <p className="text-small text-muted-foreground">{t('grants.reviews.departmentHint')}</p>
            {err('holders')}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="campaign-reviewer">{t('grants.reviews.reviewerRule')}</Label>
              <select
                id="campaign-reviewer"
                className={SELECT}
                value={reviewer}
                onChange={(e) => setReviewer(e.target.value as CampaignBody['reviewer'])}
              >
                <option value="owner">{t('grants.reviews.byOwner')}</option>
                <option value="manager">{t('grants.reviews.byManager')}</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="campaign-default">{t('grants.reviews.defaultRule')}</Label>
              <select
                id="campaign-default"
                className={SELECT}
                value={fallback}
                onChange={(e) => setFallback(e.target.value as CampaignBody['default'])}
              >
                <option value="keep">{t('grants.reviews.defaultKeep')}</option>
                <option value="revoke">{t('grants.reviews.defaultRevoke')}</option>
              </select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="campaign-deadline">{t('grants.reviews.deadline')}</Label>
            <Input
              id="campaign-deadline"
              type="date"
              min={new Date(opened).toISOString().slice(0, 10)}
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
              aria-invalid={errors.deadline ? true : undefined}
              aria-describedby={errors.deadline ? 'campaign-deadline-error' : undefined}
            />
            {err('deadline')}
          </div>
        </form>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t('grants.endDate.cancel')}
          </Button>
          <Button type="submit" form="campaign-form" disabled={create.isPending}>
            {t('grants.reviews.start')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Console page: review campaigns (managers start and follow them, reviewers find theirs). */
export function AccessReviewsPage() {
  const { t } = useTranslation()
  const campaigns = useCampaigns()
  const [creating, setCreating] = useState(false)
  if (campaigns.isError) return <ErrorState error={campaigns.error} onRetry={() => void campaigns.refetch()} />
  const items = campaigns.data?.items ?? []
  const manager = campaigns.data?.can_manage ?? false
  return (
    <PageLayout
      title={t('grants.reviews.pageTitle')}
      description={t('grants.reviews.pageDescription')}
      actions={
        manager ? (
          <Button type="button" size="sm" onClick={() => setCreating(true)}>
            <Plus aria-hidden />
            {t('grants.reviews.new')}
          </Button>
        ) : null
      }
    >
      {campaigns.isPending ? (
        <Skeleton className="h-32 w-full" />
      ) : items.length === 0 ? (
        <EmptyState icon={<ClipboardCheck className="size-6 text-muted-foreground" aria-hidden />} title={t('grants.reviews.empty')} />
      ) : (
        <div className="rounded-lg border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('grants.reviews.name')}</TableHead>
                <TableHead>{t('grants.reviews.statusLabel')}</TableHead>
                <TableHead>{t('grants.reviews.deadline')}</TableHead>
                <TableHead>{t('grants.reviews.progress')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((c) => (
                <TableRow key={c.id}>
                  <TableCell>
                    <Link to="/access/reviews/$id" params={{ id: c.id }} className="font-medium text-foreground hover:text-signal">
                      {c.name}
                    </Link>
                  </TableCell>
                  <TableCell>{t(`grants.reviews.status.${c.status}`)}</TableCell>
                  <TableCell>{secondsDay(c.deadline)}</TableCell>
                  <TableCell className="text-small text-muted-foreground">
                    {c.counts
                      ? t('grants.reviews.decidedOf', { decided: c.counts.decided, total: c.counts.items })
                      : t('grants.reviews.yours', { count: c.to_review ?? 0 })}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {creating ? <NewCampaignDialog onClose={() => setCreating(false)} /> : null}
    </PageLayout>
  )
}

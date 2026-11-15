import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Download } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { ErrorState } from '@/components/ErrorState'
import { FactList, PageLayout } from '@/components/patterns'
import { SectionCard } from '@/components/patterns/SectionCard'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { ReauthDialog } from '@/features/me/ReauthDialog'
import { accessApi } from './api'
import { secondsDay, useCampaign } from './hooks'
import { ReviewItemsTable } from './ReviewItemsTable'

function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function ReportMenu({ id }: { id: string }) {
  const { t } = useTranslation()
  const [pending, setPending] = useState<'json' | 'csv' | null>(null)
  async function run(format: 'json' | 'csv') {
    try {
      const { blob, name } = await accessApi.report(id, format)
      saveBlob(blob, name)
    } catch (e) {
      if (isApiError(e) && e.code === 'reauth_required') setPending(format)
      else toast.error(isApiError(e) ? e.message : t('grants.reviews.reportFailed'))
    }
  }
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="outline" size="sm">
            <Download aria-hidden />
            {t('grants.reviews.report')}
            <ChevronDown aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => void run('json')}>{t('grants.reviews.reportJson')}</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => void run('csv')}>{t('grants.reviews.reportCsv')}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ReauthDialog
        open={pending !== null}
        body={t('grants.reviews.reauthBody')}
        onCancel={() => setPending(null)}
        onConfirmed={() => {
          const format = pending
          setPending(null)
          if (format) void run(format)
        }}
      />
    </>
  )
}

/** One campaign: its items with decisions; managers close it and export the report. */
export function ReviewCampaignPage({ id }: { id: string }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const query = useCampaign(id)
  const [confirming, setConfirming] = useState(false)
  const close = useMutation({
    mutationFn: () => accessApi.closeCampaign(id),
    onSuccess: ({ failed }) => {
      void qc.invalidateQueries({ queryKey: ['access'] })
      if (failed.length) toast.error(t('grants.reviews.closeIncomplete', { count: failed.length }))
      else toast.success(t('grants.reviews.closed'))
    },
    onError: (e) => toast.error(isApiError(e) ? e.message : t('grants.reviews.closeFailed')),
  })
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  if (query.isPending) return <Skeleton className="h-64 w-full" />
  const { campaign, items, can_manage: manager } = query.data
  const counts = campaign.counts
  return (
    <PageLayout
      title={campaign.name}
      description={t('grants.reviews.campaignDescription', { deadline: secondsDay(campaign.deadline) })}
      className="space-y-6"
      actions={
        manager ? (
          <div className="flex gap-2">
            <ReportMenu id={campaign.id} />
            {campaign.status !== 'closed' ? (
              <Button type="button" size="sm" disabled={close.isPending} onClick={() => setConfirming(true)}>
                {campaign.status === 'closing' ? t('grants.reviews.resumeClose') : t('grants.reviews.close')}
              </Button>
            ) : null}
          </div>
        ) : null
      }
    >
      <SectionCard title={t('grants.reviews.summary')}>
        <FactList
          items={[
            { label: t('grants.reviews.statusLabel'), value: t(`grants.reviews.status.${campaign.status}`) },
            { label: t('grants.reviews.reviewerRule'), value: t(campaign.reviewer === 'owner' ? 'grants.reviews.byOwner' : 'grants.reviews.byManager') },
            { label: t('grants.reviews.defaultRule'), value: t(campaign.default === 'keep' ? 'grants.reviews.defaultKeep' : 'grants.reviews.defaultRevoke') },
            ...(counts
              ? [{ label: t('grants.reviews.progress'), value: t('grants.reviews.decidedOf', { decided: counts.decided, total: counts.items }) }]
              : []),
            ...(campaign.report_hash
              ? [{ label: t('grants.reviews.reportHash'), value: <span className="break-all font-mono text-caption">{campaign.report_hash}</span> }]
              : []),
          ]}
        />
      </SectionCard>
      <SectionCard title={t('grants.reviews.itemsTitle')} bodyClassName="p-0">
        <ReviewItemsTable campaignId={campaign.id} items={items} showReviewer={manager} />
      </SectionCard>
      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('grants.reviews.closeTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('grants.reviews.closeBody', {
                revoke: counts?.revoke ?? 0,
                undecided: (counts?.items ?? 0) - (counts?.decided ?? 0),
                fallback: t(campaign.default === 'keep' ? 'grants.reviews.keep' : 'grants.reviews.revoke'),
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('grants.endDate.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={() => close.mutate()}>{t('grants.reviews.close')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageLayout>
  )
}

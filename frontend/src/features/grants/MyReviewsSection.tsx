import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { SectionCard } from '@/components/patterns/SectionCard'
import { accessApi } from './api'
import { secondsDay, useCampaigns } from './hooks'
import { ReviewItemsTable } from './ReviewItemsTable'
import type { Campaign } from './types'

function CampaignItems({ campaign }: { campaign: Campaign }) {
  const { t } = useTranslation()
  const detail = useQuery({
    queryKey: ['access', 'reviews', campaign.id],
    queryFn: ({ signal }) => accessApi.campaign(campaign.id, signal),
    retry: false,
  })
  const items = (detail.data?.items ?? []).filter((i) => i.can_decide || i.decision)
  if (!items.length) return null
  return (
    <div className="space-y-2">
      <p className="text-body font-medium text-foreground">
        {t('grants.reviews.portalCampaign', { name: campaign.name, deadline: secondsDay(campaign.deadline) })}
      </p>
      <div className="rounded-lg border">
        <ReviewItemsTable campaignId={campaign.id} items={items} showDn={false} />
      </div>
    </div>
  )
}

/** Portal: access reviews assigned to the signed-in person (hidden when there are none). */
export function MyReviewsSection({ enabled }: { enabled: boolean }) {
  const { t } = useTranslation()
  const campaigns = useCampaigns(enabled)
  const open = (campaigns.data?.items ?? []).filter((c) => c.status === 'open' && (c.to_review ?? 0) > 0)
  if (!open.length) return null
  return (
    <SectionCard id="portal-reviews" title={t('grants.reviews.portalTitle')} description={t('grants.reviews.portalDescription')}>
      <div className="space-y-5">
        {open.map((c) => (
          <CampaignItems key={c.id} campaign={c} />
        ))}
      </div>
    </SectionCard>
  )
}

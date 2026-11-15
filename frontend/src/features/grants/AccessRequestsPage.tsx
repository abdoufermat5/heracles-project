import { useTranslation } from 'react-i18next'
import { PageLayout } from '@/components/patterns'
import { ApprovalsList, MyRequestsSection } from './RequestsSections'

/** Console page: requests waiting for the caller, and their own requests. */
export function AccessRequestsPage() {
  const { t } = useTranslation()
  return (
    <PageLayout title={t('grants.approvals.pageTitle')} description={t('grants.approvals.pageDescription')} className="space-y-6">
      <ApprovalsList />
      <MyRequestsSection />
    </PageLayout>
  )
}

import { Lock } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { useTranslation } from 'react-i18next'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/ui/empty-state'
import { PageLayout } from '@/components/patterns'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ExportTab } from './ExportTab'
import { useIoAccess } from './hooks'
import { ImportCsvTab } from './ImportCsvTab'
import { ImportLdifTab } from './ImportLdifTab'

type TabId = 'export' | 'ldif' | 'csv'

export function IoPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = useIoAccess()

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />

  const tabs: { id: TabId; label: string }[] = []
  if (data?.ldif_export) tabs.push({ id: 'export', label: t('io.tabs.export') })
  if (data?.ldif_import) tabs.push({ id: 'ldif', label: t('io.tabs.ldif') })
  if (data?.csv_import) tabs.push({ id: 'csv', label: t('io.tabs.csv') })

  return (
    <PageLayout title={t('io.title')} description={t('io.description')}>
      {isPending ? (
        <div className="space-y-3" aria-busy="true" aria-label={t('common.loading')}>
          <Skeleton className="h-9 w-72" />
          <Skeleton className="h-64" />
        </div>
      ) : tabs.length === 0 ? (
        <EmptyState
          icon={<Lock aria-hidden />}
          title={t('io.noAccess')}
          description={t('io.noAccessHelp')}
          action={
            <Button asChild variant="outline" size="sm">
              <Link to="/">{t('onboarding.next.dashboard')}</Link>
            </Button>
          }
        />
      ) : (
        <Tabs defaultValue={tabs[0]?.id}>
          <TabsList aria-label={t('io.title')}>
            {tabs.map((tab) => (
              <TabsTrigger key={tab.id} value={tab.id}>
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
          {data?.ldif_export && (
            <TabsContent value="export">
              <ExportTab />
            </TabsContent>
          )}
          {data?.ldif_import && (
            <TabsContent value="ldif">
              <ImportLdifTab />
            </TabsContent>
          )}
          {data?.csv_import && (
            <TabsContent value="csv">
              <ImportCsvTab />
            </TabsContent>
          )}
        </Tabs>
      )}
    </PageLayout>
  )
}


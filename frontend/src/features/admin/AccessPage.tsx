import { useTranslation } from 'react-i18next'
import { PageLayout } from '@/components/patterns'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CheckRightsPanel } from '@/features/access/CheckRightsPanel'
import { RolesPanel } from '@/features/access/RolesPanel'
import { WhoHasAccessPanel } from '@/features/access/WhoHasAccessPanel'

export function AccessPage() {
  const { t } = useTranslation()
  return (
    <PageLayout title={t('accessUI.title')} description={t('accessUI.description')}>
      <Tabs defaultValue="roles">
        <TabsList>
          <TabsTrigger value="roles">{t('accessUI.tabs.roles')}</TabsTrigger>
          <TabsTrigger value="people">{t('accessUI.tabs.people')}</TabsTrigger>
          <TabsTrigger value="check">{t('accessUI.tabs.check')}</TabsTrigger>
        </TabsList>
        <TabsContent value="roles" className="pt-4">
          <RolesPanel />
        </TabsContent>
        <TabsContent value="people" className="pt-4">
          <WhoHasAccessPanel />
        </TabsContent>
        <TabsContent value="check" className="pt-4">
          <CheckRightsPanel />
        </TabsContent>
      </Tabs>
    </PageLayout>
  )
}

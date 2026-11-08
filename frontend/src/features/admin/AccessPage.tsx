import { useTranslation } from 'react-i18next'
import { PageHeader } from '@/components/ui/page-header'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AssignmentsPanel } from './AssignmentsPanel'
import { CheckRightsPanel } from './CheckRightsPanel'
import { RolesPanel } from './RolesPanel'

export function AccessPage() {
  const { t } = useTranslation()
  return (
    <div className="space-y-2">
      <PageHeader title={t('acl.title')} description={t('acl.description_page')} />
      <Tabs defaultValue="roles">
        <TabsList>
          <TabsTrigger value="roles">{t('acl.tabRoles')}</TabsTrigger>
          <TabsTrigger value="assignments">{t('acl.tabAssignments')}</TabsTrigger>
          <TabsTrigger value="check">{t('acl.tabCheck')}</TabsTrigger>
        </TabsList>
        <TabsContent value="roles" className="pt-3">
          <RolesPanel />
        </TabsContent>
        <TabsContent value="assignments" className="pt-3">
          <AssignmentsPanel />
        </TabsContent>
        <TabsContent value="check" className="pt-3">
          <CheckRightsPanel />
        </TabsContent>
      </Tabs>
    </div>
  )
}

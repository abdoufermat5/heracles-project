import { Download } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ldifExportUrl, type LdifScope } from './api'
import { FormField, NATIVE_SELECT, Notice } from './parts'

export function ExportTab() {
  const { t } = useTranslation()
  const [base, setBase] = useState('')
  const [filter, setFilter] = useState('(objectClass=*)')
  const [scope, setScope] = useState<LdifScope>('sub')
  const [wrap, setWrap] = useState(76)

  const url = ldifExportUrl({ base, filter: filter || '(objectClass=*)', scope, wrap })

  return (
    <Card>
      <CardHeader className="border-b">
        <CardTitle>{t('io.export.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 p-4">
        <Notice>{t('io.export.notice')}</Notice>
        <div className="grid gap-4 md:grid-cols-2">
          <FormField id="export-base" label={t('io.export.base')} hint={t('io.export.baseHelp')}>
            <Input
              id="export-base"
              className="font-mono"
              value={base}
              onChange={(e) => setBase(e.target.value)}
              aria-describedby="export-base-hint"
            />
          </FormField>
          <FormField id="export-filter" label={t('io.export.filter')} hint={t('io.export.filterHelp')}>
            <Input
              id="export-filter"
              className="font-mono"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              aria-describedby="export-filter-hint"
            />
          </FormField>
          <FormField id="export-scope" label={t('io.export.scope')}>
            <select
              id="export-scope"
              className={NATIVE_SELECT}
              value={scope}
              onChange={(e) => setScope(e.target.value as LdifScope)}
            >
              <option value="base">{t('io.export.scopeBase')}</option>
              <option value="one">{t('io.export.scopeOne')}</option>
              <option value="sub">{t('io.export.scopeSub')}</option>
            </select>
          </FormField>
          <FormField id="export-wrap" label={t('io.export.wrap')} hint={t('io.export.wrapHelp')}>
            <Input
              id="export-wrap"
              type="number"
              min={0}
              max={1000}
              value={wrap}
              onChange={(e) => setWrap(Math.max(0, Math.min(1000, Number(e.target.value) || 0)))}
              aria-describedby="export-wrap-hint"
            />
          </FormField>
        </div>
        <Button asChild>
          <a href={url} download="export.ldif">
            <Download aria-hidden />
            {t('io.export.download')}
          </a>
        </Button>
      </CardContent>
    </Card>
  )
}

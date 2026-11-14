import { Download } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { isApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ldifExport, type LdifScope } from './api'
import { FormField, NATIVE_SELECT, Notice } from './parts'
import { checkExport, type ExportErrors } from './rules'

type Field = keyof ExportErrors

/** Save a blob under a name, through a temporary link. */
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

export function ExportTab() {
  const { t } = useTranslation()
  const [base, setBase] = useState('')
  const [filter, setFilter] = useState('(objectClass=*)')
  const [scope, setScope] = useState<LdifScope>('sub')
  const [wrap, setWrap] = useState('76')
  const [touched, setTouched] = useState<Partial<Record<Field, boolean>>>({})
  const [attempted, setAttempted] = useState(false)
  const [refused, setRefused] = useState<ExportErrors>({})
  const [failure, setFailure] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const problems = checkExport({ base, filter, wrap })
  const count = Object.keys(problems).length
  const touch = (field: Field) => setTouched((s) => ({ ...s, [field]: true }))
  // what the server refused stays until the field changes
  const change = (field: Field, set: (v: string) => void) => (v: string) => {
    set(v)
    setRefused((r) => ({ ...r, [field]: undefined }))
    setFailure(null)
  }
  const shown = (field: Field): string | undefined =>
    (touched[field] || attempted ? problems[field] : undefined) ?? refused[field]
  const baseError = shown('base')
  const filterError = shown('filter')
  const wrapError = shown('wrap')

  const download = async () => {
    if (count > 0) {
      setAttempted(true)
      return
    }
    setPending(true)
    setFailure(null)
    try {
      const blob = await ldifExport({
        base,
        filter: filter.trim() || '(objectClass=*)',
        scope,
        wrap: Number(wrap),
      })
      saveBlob(blob, 'export.ldif')
    } catch (e) {
      if (!isApiError(e)) setFailure(t('common.error'))
      else if (e.status === 404) setRefused({ base: t('io.errors.baseNotFound') })
      else if (e.fields.base) setRefused({ base: t('validation.format.dn') })
      else if (e.fields.filter)
        setRefused({
          filter: /too many/i.test(e.fields.filter)
            ? t('io.errors.tooManyEntries')
            : t('validation.format.ldap_filter'),
        })
      else setFailure(e.message)
    } finally {
      setPending(false)
    }
  }

  return (
    <Card>
      <CardHeader className="border-b">
        <CardTitle>{t('io.export.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 p-4">
        <Notice>{t('io.export.notice')}</Notice>
        <div className="grid gap-4 md:grid-cols-2">
          <FormField
            id="export-base"
            label={t('io.export.base')}
            hint={t('io.export.baseHelp')}
            error={baseError}
          >
            <Input
              id="export-base"
              className="font-mono"
              value={base}
              aria-invalid={!!baseError}
              aria-describedby={baseError ? 'export-base-error export-base-hint' : 'export-base-hint'}
              onBlur={() => touch('base')}
              onChange={(e) => change('base', setBase)(e.target.value)}
            />
          </FormField>
          <FormField
            id="export-filter"
            label={t('io.export.filter')}
            hint={t('io.export.filterHelp')}
            error={filterError}
          >
            <Input
              id="export-filter"
              className="font-mono"
              value={filter}
              aria-invalid={!!filterError}
              aria-describedby={
                filterError ? 'export-filter-error export-filter-hint' : 'export-filter-hint'
              }
              onBlur={() => touch('filter')}
              onChange={(e) => change('filter', setFilter)(e.target.value)}
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
          <FormField
            id="export-wrap"
            label={t('io.export.wrap')}
            hint={t('io.export.wrapHelp')}
            error={wrapError}
          >
            <Input
              id="export-wrap"
              inputMode="numeric"
              value={wrap}
              aria-invalid={!!wrapError}
              aria-describedby={wrapError ? 'export-wrap-error export-wrap-hint' : 'export-wrap-hint'}
              onBlur={() => touch('wrap')}
              onChange={(e) => change('wrap', setWrap)(e.target.value)}
            />
          </FormField>
        </div>
        {failure && <Notice tone="error">{failure}</Notice>}
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => void download()} disabled={pending}>
            <Download aria-hidden />
            {t('io.export.download')}
          </Button>
          {attempted && count > 0 && (
            <p role="alert" className="text-small text-destructive">
              {t('io.errors.blocked', { count })}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

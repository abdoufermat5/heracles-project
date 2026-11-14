import { useNavigate, Link } from '@tanstack/react-router'
import { keepPreviousData, useQuery, type UseQueryResult } from '@tanstack/react-query'
import { ChevronLeft, Save, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { useMe, useCreateObject } from '@/api/hooks'
import type { TypeDescriptor } from '@/api/types'
import { DepartmentPicker } from '@/components/fields/RefFields'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/ErrorState'
import { typeLabel } from '@/lib/labels'
import { allAttributes, defaultValue, splitFieldKey, type FormValues } from '@/lib/objects'
import { useScope } from '@/lib/scope'
import { makeResolver } from '@/lib/validation'
import {
  objectKeys,
  objectsApi,
  useTemplateFields,
  useTemplates,
  type ResolvedValues,
} from './api'
import { EditorSection } from './EditorSection'
import { TemplatePicker } from './TemplatePicker'
import {
  compactValues,
  emptyFieldValues,
  fieldsDescriptor,
  templateCreateTabs,
} from './templateForm'

interface Props {
  desc: TypeDescriptor
  templateDn: string
  onTemplateChange: (dn: string | null) => void
}

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

/**
 * Create mode with a template: asks only for the fields the template leaves open,
 * previews the resolved values live and creates the object (`template` in the body).
 */
export function TemplateFillForm({ desc, templateDn, onTemplateChange }: Props) {
  const fields = useTemplateFields(desc.name, templateDn)
  const templates = useTemplates(desc.name)
  const { t } = useTranslation()

  if (fields.isError) {
    return <ErrorState error={fields.error} onRetry={() => void fields.refetch()} />
  }
  if (!fields.data) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label={t('common.loading')}>
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full rounded-md" />
      </div>
    )
  }
  const name = templates.data?.find((x) => x.dn === templateDn)?.name ?? ''
  return (
    <FillInner
      key={templateDn}
      desc={desc}
      templateDn={templateDn}
      templateName={name}
      fields={fields.data.fields}
      onTemplateChange={onTemplateChange}
    />
  )
}

function FillInner({
  desc,
  templateDn,
  templateName,
  fields,
  onTemplateChange,
}: Props & { templateName: string; fields: Record<string, string[]> }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const scope = useScope()
  const me = useMe()
  const type = desc.name
  const create = useCreateObject(type)

  const fd = useMemo(() => fieldsDescriptor(desc, fields), [desc, fields])
  const active = useMemo(() => Object.fromEntries(fd.tabs.map((tb) => [tb.name, true])), [fd])
  const resolver = useMemo(() => makeResolver(fd, () => active), [fd, active])
  const form = useForm<FormValues>({
    defaultValues: emptyFieldValues(fd, defaultValue),
    resolver,
    mode: 'onTouched',
    reValidateMode: 'onChange',
  })
  const [base, setBase] = useState<string>(scope.base ?? me.data?.base ?? '')
  const current = useWatch({ control: form.control }) as FormValues
  const compact = useMemo(() => compactValues(current), [current])
  const debounced = useDebounced(JSON.stringify(compact))
  const hasFields = fd.tabs.length > 0

  const preview = useQuery({
    queryKey: [...objectKeys.templateFields(type, templateDn), 'preview', debounced],
    queryFn: () => objectsApi.previewTemplate(type, templateDn, JSON.parse(debounced) as typeof compact),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 0,
  })

  const submit = form.handleSubmit(
    async (values) => {
      try {
        const res = await create.mutateAsync({
          base,
          template: templateDn,
          tabs: templateCreateTabs(values),
        })
        toast.success(t('templates.created_object', { type: typeLabel(t, desc) }))
        void navigate({ to: '/types/$type/$dn', params: { type, dn: res.dn } })
      } catch (e) {
        if (isApiError(e) && e.code === 'validation') {
          let other: string | null = null
          for (const [key, message] of Object.entries(e.fields)) {
            const parts = splitFieldKey(key)
            if (parts && form.getValues(`${parts.tab}.${parts.attr}` as never) !== undefined) {
              form.setError(key as never, { type: 'server', message })
            } else {
              other ??= message
            }
          }
          toast.error(other ?? t('editor.validationFailed'))
        } else {
          toast.error(isApiError(e) ? e.message : t('common.error'))
        }
      }
    },
    () => toast.error(t('editor.fixErrors')),
  )

  return (
    <form onSubmit={(e) => void submit(e)} noValidate className="flex flex-1 flex-col space-y-4">
      <header className="space-y-3 border-b pb-4">
        <Link
          to="/types/$type"
          params={{ type }}
          className="inline-flex items-center gap-1 text-body text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="size-3.5" aria-hidden />
          <span>{t('editor.backToList', { type: typeLabel(t, desc) })}</span>
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-lg font-semibold tracking-tight text-foreground">
                {t('editor.newTitle', { type: typeLabel(t, desc) })}
              </h1>
              <Badge variant="neutral">{templateName}</Badge>
            </div>
            <p className="text-body text-muted-foreground">
              {t('templates.fillHelp', { name: templateName })}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => onTemplateChange(null)}>
              <X aria-hidden />
              {t('common.cancel')}
            </Button>
            <Button type="submit" size="sm" disabled={form.formState.isSubmitting || !base}>
              <Save aria-hidden />
              {t('templates.createFrom', { type: typeLabel(t, desc) })}
            </Button>
          </div>
        </div>
      </header>

      <TemplatePicker type={type} selected={templateDn} onChange={onTemplateChange} />

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-4">
          <section className="rounded-md border bg-card p-4">
            <div className="space-y-1.5">
              <Label htmlFor="tpl-base" className="text-xs font-medium text-muted-foreground">
                {t('templates.department')}
              </Label>
              <DepartmentPicker id="tpl-base" value={base || null} onChange={setBase} />
            </div>
          </section>

          {hasFields ? (
            fd.tabs.flatMap((tb) =>
              tb.sections.map((sec) => (
                <EditorSection
                  key={`${tb.name}-${sec.name}`}
                  section={sec}
                  tabName={tb.name}
                  control={form.control}
                  acl={undefined}
                  isCreate
                  readOnlyMode={false}
                />
              )),
            )
          ) : (
            <p className="rounded-md border border-dashed bg-card p-4 text-body text-muted-foreground">
              {t('templates.noFields')}
            </p>
          )}
        </div>

        <aside
          aria-label={t('templates.previewTitle')}
          className="rounded-md border bg-card lg:sticky lg:top-4"
        >
          <div className="border-b px-4 py-2.5">
            <h2 className="text-body font-semibold text-foreground">{t('templates.previewTitle')}</h2>
            <p className="text-xs text-muted-foreground">{t('templates.previewHelp')}</p>
          </div>
          <PreviewBody desc={desc} query={preview} />
        </aside>
      </div>
    </form>
  )
}

function formatValue(v: unknown): string {
  if (Array.isArray(v)) return v.map(formatValue).join(', ')
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function PreviewBody({
  desc,
  query,
}: {
  desc: TypeDescriptor
  query: UseQueryResult<{ tabs: ResolvedValues }>
}) {
  const { t } = useTranslation()
  if (query.isError) {
    return (
      <p className="p-4 text-body text-muted-foreground">
        {isApiError(query.error) && query.error.code === 'validation'
          ? t('templates.previewEmpty')
          : t('templates.previewFailed')}
      </p>
    )
  }
  if (!query.data) {
    return (
      <div className="space-y-2 p-4" aria-busy="true" aria-label={t('common.loading')}>
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-4 w-3/4" />
      </div>
    )
  }
  const rows: Array<{ key: string; label: string; value: string }> = []
  for (const [tabName, values] of Object.entries(query.data.tabs)) {
    const tab = desc.tabs.find((x) => x.name === tabName)
    const attrs = tab ? allAttributes(tab) : []
    for (const [name, value] of Object.entries(values)) {
      const text = formatValue(value)
      if (text === '') continue
      const attr = attrs.find((a) => a.name === name)
      rows.push({ key: `${tabName}.${name}`, label: attr?.label ?? name, value: attr?.kind === 'password' ? '••••••••' : text })
    }
  }
  if (rows.length === 0) {
    return <p className="p-4 text-body text-muted-foreground">{t('templates.previewEmpty')}</p>
  }
  return (
    <dl className="divide-y text-body" data-testid="template-preview">
      {rows.map((r) => (
        <div key={r.key} className="grid grid-cols-[8rem_minmax(0,1fr)] gap-2 px-4 py-2">
          <dt className="truncate text-xs text-muted-foreground">{r.label}</dt>
          <dd className="font-mono text-xs break-words text-foreground">{r.value}</dd>
        </div>
      ))}
    </dl>
  )
}

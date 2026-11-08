import { Link, useNavigate } from '@tanstack/react-router'
import { ChevronLeft, Plus, Save, Trash2, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { useMe, useTypeDescriptor } from '@/api/hooks'
import type { AttributeDescriptor, TypeDescriptor } from '@/api/types'
import { DepartmentPicker } from '@/components/fields/RefFields'
import { ErrorState } from '@/components/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { splitFieldKey } from '@/lib/objects'
import { useScope } from '@/lib/scope'
import { useTemplate, useTemplateMutations, type TemplateDetail } from './api'
import { EditorTabNav } from './EditorTabNav'
import { MaskHelp } from './MaskHelp'
import {
  isMultiText,
  maskRequestTabs,
  maskValuesFromDetail,
  templateAttributes,
  type MaskValue,
  type MaskValues,
} from './templateForm'

interface PageProps {
  type: string
  /** DN of the template to edit, `null` to create one. */
  dn: string | null
}

/** Editor of the templates of one type ("template mode": every field is free text with masks). */
export function TemplateEditorPage({ type, dn }: PageProps) {
  const desc = useTypeDescriptor(type)
  const tpl = useTemplate(type, dn)
  const { t } = useTranslation()

  if (desc.isError) return <ErrorState error={desc.error} onRetry={() => void desc.refetch()} />
  if (dn !== null && tpl.isError) return <ErrorState error={tpl.error} onRetry={() => void tpl.refetch()} />
  if (!desc.data || (dn !== null && !tpl.data)) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label={t('common.loading')}>
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full rounded-md" />
      </div>
    )
  }
  return <TemplateForm key={dn ?? 'new'} desc={desc.data} template={tpl.data ?? null} />
}

function TemplateForm({ desc, template }: { desc: TypeDescriptor; template: TemplateDetail | null }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const scope = useScope()
  const me = useMe()
  const type = desc.name
  const isCreate = template === null
  const { create, patch } = useTemplateMutations(type)

  const tabs = useMemo(() => desc.tabs.filter((tb) => templateAttributes(tb).length > 0), [desc])
  const [values, setValues] = useState<MaskValues>(() => maskValuesFromDetail(desc, template?.tabs))
  const [active, setActive] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(desc.tabs.map((tb) => [tb.name, template ? (template.tabs[tb.name]?.active ?? false) : !tb.optional])),
  )
  const [name, setName] = useState(template?.name ?? '')
  const [base, setBase] = useState(template?.base ?? scope.base ?? me.data?.base ?? '')
  const [tab, setTab] = useState(tabs[0]?.name ?? 'main')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const errorsByTab = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const key of Object.keys(errors)) {
      const parts = splitFieldKey(key)
      if (parts) counts[parts.tab] = (counts[parts.tab] ?? 0) + 1
    }
    return counts
  }, [errors])

  const setValue = (tabName: string, attr: string, v: MaskValue) =>
    setValues((cur) => ({ ...cur, [tabName]: { ...cur[tabName], [attr]: v } }))

  const save = async () => {
    setErrors({})
    const tabsBody = maskRequestTabs(desc, values, active, !isCreate)
    try {
      if (template) {
        await patch.mutateAsync({ dn: template.dn, body: { name: name.trim(), tabs: tabsBody } })
        toast.success(t('templates.saved'))
      } else {
        await create.mutateAsync({ name: name.trim(), base, tabs: tabsBody })
        toast.success(t('templates.created'))
      }
      void navigate({ to: '/types/$type', params: { type }, search: { view: 'templates' } })
    } catch (e) {
      if (isApiError(e) && e.code === 'validation') {
        setErrors(e.fields)
        const first = Object.keys(e.fields).map((k) => splitFieldKey(k)?.tab).find((x) => x && tabs.some((tb) => tb.name === x))
        if (first) setTab(first)
        toast.error(t('editor.validationFailed'))
      } else {
        toast.error(isApiError(e) ? e.message : t('common.error'))
      }
    }
  }

  const current = tabs.find((tb) => tb.name === tab) ?? tabs[0]
  const busy = create.isPending || patch.isPending

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        void save()
      }}
      noValidate
      className="flex flex-1 flex-col space-y-4"
    >
      <header className="space-y-3 border-b pb-4">
        <Link
          to="/types/$type"
          params={{ type }}
          search={{ view: 'templates' }}
          className="inline-flex items-center gap-1 text-body text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="size-3.5" aria-hidden />
          <span>{t('templates.backToList', { type: desc.label })}</span>
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-lg font-semibold tracking-tight text-foreground">
                {template
                  ? t('templates.editTitle', { name: template.name })
                  : t('templates.newTitle', { type: desc.label })}
              </h1>
              <Badge variant="neutral">{t('templates.badge')}</Badge>
            </div>
            <p className="text-body text-muted-foreground">{t('templates.editHelp')}</p>
          </div>
          <div className="flex items-center gap-2">
            <MaskHelp />
            <Button type="button" variant="ghost" size="sm" asChild>
              <Link to="/types/$type" params={{ type }} search={{ view: 'templates' }}>
                <X aria-hidden />
                {t('common.cancel')}
              </Link>
            </Button>
            <Button type="submit" size="sm" disabled={busy}>
              <Save aria-hidden />
              {isCreate ? t('common.create') : t('common.save')}
            </Button>
          </div>
        </div>
      </header>

      <section className="grid gap-4 rounded-md border bg-card p-4 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="tpl-name" className="text-xs font-medium text-muted-foreground">
            {t('templates.name')} <span aria-hidden className="text-destructive">*</span>
          </Label>
          <Input
            id="tpl-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={errors.name ? true : undefined}
            className="h-8 text-body"
          />
          {errors.name && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {errors.name}
            </p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="tpl-department" className="text-xs font-medium text-muted-foreground">
            {t('templates.department')}
          </Label>
          <DepartmentPicker
            id="tpl-department"
            value={base || null}
            onChange={setBase}
            disabled={!isCreate}
          />
        </div>
      </section>

      <div className="flex flex-col items-start gap-4 pt-1 lg:flex-row">
        <EditorTabNav
          tabs={tabs}
          currentTab={tab}
          onSelectTab={setTab}
          active={active}
          errorsByTab={errorsByTab}
          dirtyTabs={new Set()}
        />
        <div
          role="tabpanel"
          id={`panel-${current?.name}`}
          aria-labelledby={`tab-${current?.name}`}
          className="w-full min-w-0 flex-1 space-y-4"
        >
          {current?.optional && (
            <div className="flex items-center justify-between rounded-md border bg-card p-4">
              <div>
                <p className="text-body font-medium text-foreground">{t('templates.includeTab', { tab: current.label })}</p>
                <p className="text-xs text-muted-foreground">{t('templates.includeTabHelp')}</p>
              </div>
              <Switch
                checked={active[current.name] ?? false}
                onCheckedChange={(v) => setActive((a) => ({ ...a, [current.name]: v }))}
                aria-label={t('templates.includeTab', { tab: current.label })}
              />
            </div>
          )}
          {current && (active[current.name] ?? false) &&
            current.sections.map((sec) => {
              const attrs = sec.attributes.filter((a) => templateAttributes(current).includes(a))
              if (attrs.length === 0) return null
              return (
                <section key={sec.name} aria-labelledby={`tsec-${current.name}-${sec.name}`} className="rounded-md border bg-card">
                  <div className="flex h-10 items-center border-b px-4">
                    <h2 id={`tsec-${current.name}-${sec.name}`} className="text-body font-semibold text-foreground">
                      {sec.label}
                    </h2>
                  </div>
                  <div className="grid grid-cols-1 gap-x-8 gap-y-4 p-4 md:grid-cols-2">
                    {attrs.map((a) => (
                      <MaskField
                        key={a.name}
                        tab={current.name}
                        attr={a}
                        value={values[current.name]?.[a.name] ?? (isMultiText(a) ? [] : '')}
                        error={errors[`${current.name}.${a.name}`]}
                        onChange={(v) => setValue(current.name, a.name, v)}
                      />
                    ))}
                  </div>
                </section>
              )
            })}
        </div>
      </div>
    </form>
  )
}

interface MaskFieldProps {
  tab: string
  attr: AttributeDescriptor
  value: MaskValue
  error?: string
  onChange: (v: MaskValue) => void
}

/** One attribute of a template: a free text input (or a list of them) accepting masks. */
function MaskField({ tab, attr, value, error, onChange }: MaskFieldProps) {
  const { t } = useTranslation()
  const id = `tpl-${tab}-${attr.name}`
  const items = Array.isArray(value) ? value : [value]
  const multi = isMultiText(attr)

  return (
    <div className={multi ? 'space-y-1.5 md:col-span-2' : 'space-y-1.5'} data-field={`${tab}.${attr.name}`}>
      <Label htmlFor={`${id}-0`} className="text-xs font-medium text-muted-foreground">
        {attr.label}
      </Label>
      {multi ? (
        <div className="space-y-1.5">
          {items.map((item, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <Input
                id={`${id}-${i}`}
                value={item}
                onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))}
                placeholder={t('templates.maskPlaceholder')}
                aria-invalid={error ? true : undefined}
                className="h-8 font-mono text-body"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={t('templates.removeValue')}
                onClick={() => onChange(items.filter((_, j) => j !== i))}
              >
                <Trash2 aria-hidden />
              </Button>
            </div>
          ))}
          <Button type="button" variant="outline" size="sm" onClick={() => onChange([...items, ''])}>
            <Plus aria-hidden />
            {t('templates.addValue')}
          </Button>
        </div>
      ) : (
        <Input
          id={`${id}-0`}
          value={items[0] ?? ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t('templates.maskPlaceholder')}
          aria-invalid={error ? true : undefined}
          className="h-8 font-mono text-body"
        />
      )}
      {error && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

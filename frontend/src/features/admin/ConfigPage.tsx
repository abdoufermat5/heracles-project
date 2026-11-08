import { Lock, Save, Undo2 } from 'lucide-react'
import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { ErrorState } from '@/components/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/ui/page-header'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { fromLines, nextDraft, normalise, sectionFields, toLines } from './configModel'
import { HooksSection } from './HooksSection'
import { useConfig, useSaveConfig } from './hooks'
import type { ConfigField, ConfigValue, ConfigView } from './types'

const UNSET = '__unset__'

function FieldControl({
  field,
  value,
  readOnly,
  error,
  onChange,
}: {
  field: ConfigField
  value: ConfigValue
  readOnly: boolean
  error?: string
  onChange: (v: ConfigValue) => void
}) {
  const { t } = useTranslation()
  const id = useId()
  const label = t(`config.field.${field.key}`)
  const disabled = readOnly || field.hidden

  let control: React.ReactNode
  switch (field.kind) {
    case 'bool':
      control = (
        <Switch
          id={id}
          checked={value === true}
          disabled={disabled}
          onCheckedChange={onChange}
          aria-invalid={!!error}
        />
      )
      break
    case 'int':
      control = (
        <Input
          id={id}
          type="number"
          min={0}
          className="max-w-40 tabular-nums"
          value={typeof value === 'number' ? String(value) : ''}
          disabled={disabled}
          aria-invalid={!!error}
          onChange={(e) => {
            const n = e.target.value === '' ? null : Number(e.target.value)
            onChange(n !== null && Number.isNaN(n) ? null : n)
          }}
        />
      )
      break
    case 'select':
      control = (
        <Select
          value={typeof value === 'string' && value !== '' ? value : UNSET}
          disabled={disabled}
          onValueChange={(v) => onChange(v === UNSET ? '' : v)}
        >
          <SelectTrigger id={id} className="w-full max-w-64" aria-invalid={!!error}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={UNSET}>{t('config.unset')}</SelectItem>
            {field.options.map((o) => (
              <SelectItem key={o} value={o}>
                {t(`config.option.${o}`, { defaultValue: o })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )
      break
    case 'list':
      control = (
        <Textarea
          id={id}
          rows={3}
          className="font-mono text-xs"
          value={toLines(value)}
          disabled={disabled}
          aria-invalid={!!error}
          aria-describedby={`${id}-hint`}
          onChange={(e) => onChange(fromLines(e.target.value))}
        />
      )
      break
    case 'text':
      control = (
        <Textarea
          id={id}
          rows={4}
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          aria-invalid={!!error}
          onChange={(e) => onChange(e.target.value)}
        />
      )
      break
    default:
      control = (
        <Input
          id={id}
          className={cn(field.kind === 'path' && 'font-mono text-xs')}
          value={field.hidden ? '' : typeof value === 'string' ? value : ''}
          placeholder={field.hidden ? t('config.hidden') : undefined}
          disabled={disabled}
          aria-invalid={!!error}
          onChange={(e) => onChange(e.target.value)}
        />
      )
  }

  return (
    <div className="grid gap-1.5 border-b border-border py-3 last:border-b-0 md:grid-cols-[minmax(0,15rem)_1fr] md:gap-6">
      <div className="space-y-1">
        <Label htmlFor={id} className="leading-snug">
          {label}
        </Label>
        {!field.honoured && (
          <div>
            <Badge variant="neutral" title={t('config.storedHelp')}>
              {t('config.stored')}
            </Badge>
          </div>
        )}
      </div>
      <div className="min-w-0 space-y-1">
        {control}
        {field.kind === 'list' && (
          <p id={`${id}-hint`} className="text-[11px] text-muted-foreground">
            {t('config.listHint')}
          </p>
        )}
        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}

function ConfigEditor({ view }: { view: ConfigView }) {
  const { t } = useTranslation()
  const save = useSaveConfig()
  const [section, setSection] = useState(view.sections[0] ?? 'core')
  const [draft, setDraft] = useState<Record<string, ConfigValue>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const readOnly = !view.can_write
  const dirty = Object.keys(draft).length

  const fields = sectionFields(view.fields, section)
  const dirtyIn = (s: string) =>
    view.fields.filter((f) => f.section === s && f.key in draft).length

  const submit = async () => {
    setErrors({})
    try {
      await save.mutateAsync(draft)
      setDraft({})
      toast.success(t('config.saved'))
    } catch (e) {
      if (isApiError(e) && Object.keys(e.fields).length > 0) {
        setErrors(e.fields)
        const first = view.fields.find((f) => f.key in e.fields)
        if (first) setSection(first.section)
      }
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[14rem_1fr]">
      <nav aria-label={t('config.sections')} className="flex flex-row flex-wrap gap-1 lg:flex-col">
        {view.sections.map((s) => {
          const count = dirtyIn(s)
          return (
            <button
              key={s}
              type="button"
              aria-current={s === section ? 'page' : undefined}
              onClick={() => setSection(s)}
              className={cn(
                'flex h-8 items-center justify-between gap-2 rounded-sm px-3 text-left text-[13px] font-medium text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring',
                s === section && 'bg-accent text-accent-foreground',
              )}
            >
              <span className="truncate">{t(`config.section.${s}`)}</span>
              {count > 0 && (
                <span className="size-1.5 shrink-0 rounded-full bg-primary" aria-label={t('config.modified')} />
              )}
            </button>
          )
        })}
      </nav>

      <section aria-labelledby="config-section-title" className="min-w-0 space-y-4">
        <div className="space-y-1">
          <h2 id="config-section-title" className="text-sm font-semibold tracking-tight">
            {t(`config.section.${section}`)}
          </h2>
          <p className="text-[13px] text-muted-foreground">{t(`config.sectionHelp.${section}`)}</p>
        </div>

        {section === 'triggers' ? (
          <HooksSection />
        ) : (
          <div className="rounded-md border bg-card px-4">
            {fields.map((f) => (
              <FieldControl
                key={f.key}
                field={f}
                value={f.key in draft ? (draft[f.key] ?? null) : normalise(f, f.value)}
                readOnly={readOnly}
                error={errors[f.key]}
                onChange={(v) => setDraft((d) => nextDraft(d, f, v))}
              />
            ))}
          </div>
        )}

        {section !== 'triggers' && (
          <div className="sticky bottom-0 flex items-center justify-end gap-2 border-t bg-background/95 py-3 backdrop-blur">
            {readOnly ? (
              <p className="mr-auto flex items-center gap-1.5 text-[13px] text-muted-foreground">
                <Lock className="size-3.5" aria-hidden />
                {t('config.readOnly')}
              </p>
            ) : (
              <p className="mr-auto text-[13px] text-muted-foreground" aria-live="polite">
                {dirty > 0 ? t('config.pending', { count: dirty }) : t('config.noChanges')}
              </p>
            )}
            <Button
              variant="outline"
              size="sm"
              disabled={dirty === 0 || save.isPending}
              onClick={() => {
                setDraft({})
                setErrors({})
              }}
            >
              <Undo2 />
              {t('config.discard')}
            </Button>
            <Button size="sm" disabled={readOnly || dirty === 0 || save.isPending} onClick={() => void submit()}>
              <Save />
              {t('common.save')}
            </Button>
          </div>
        )}
      </section>
    </div>
  )
}

export function ConfigPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = useConfig()
  return (
    <div>
      <PageHeader title={t('config.title')} description={t('config.description')} />
      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <div className="space-y-2" aria-busy="true">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <ConfigEditor view={data} />
      )}
    </div>
  )
}

import {
  Bell,
  Cpu,
  KeyRound,
  Layers,
  Lock,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  Undo2,
  X,
} from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { ErrorState } from '@/components/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
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
import { useTechnicalDetails } from '@/lib/preferences'
import { cn } from '@/lib/utils'
import {
  CONFIG_GROUPS,
  type ConfigGroupId,
  fromLines,
  groupFields,
  nextDraft,
  normalise,
  searchFields,
  toLines,
} from './configModel'
import { HooksSection } from './HooksSection'
import { useConfig, useSaveConfig } from './hooks'
import type { ConfigField, ConfigValue, ConfigView } from './types'

const UNSET = '__unset__'

const GROUP_ICONS: Record<ConfigGroupId, typeof Settings2> = {
  general: Settings2,
  security: ShieldCheck,
  passwords: KeyRound,
  notifications: Bell,
  automation: Cpu,
  advanced: Layers,
}

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
  const technical = useTechnicalDetails()
  const id = useId()
  const label = t(`config.field.${field.key}`, { defaultValue: field.key })
  const helpText = t(`settingsUI.config.help.${field.key}`, { defaultValue: '' })
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
    <div className="grid gap-1.5 border-b border-border py-3 last:border-b-0 md:grid-cols-[minmax(0,18rem)_1fr] md:gap-6">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <Label htmlFor={id} className="leading-snug font-medium">
            {label}
          </Label>
          {technical && (
            <span
              className="font-mono text-micro rounded bg-muted/60 px-1.5 py-0.5 text-muted-foreground"
              title={t('settingsUI.config.technicalKey')}
            >
              {field.key}
            </span>
          )}
        </div>
        {helpText && (
          <p className="text-caption text-muted-foreground leading-normal">
            {helpText}
          </p>
        )}
        {!field.honoured && (
          <div>
            <Badge variant="neutral" title={t('settingsUI.config.storedNotice')}>
              {t('settingsUI.config.storedBadge')}
            </Badge>
          </div>
        )}
      </div>
      <div className="min-w-0 space-y-1">
        {control}
        {field.kind === 'list' && (
          <p id={`${id}-hint`} className="text-caption text-muted-foreground">
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
  const [activeGroup, setActiveGroup] = useState<ConfigGroupId>('general')
  const [search, setSearch] = useState('')
  const [legacyFilter, setLegacyFilter] = useState('all')
  const [draft, setDraft] = useState<Record<string, ConfigValue>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const readOnly = !view.can_write
  const dirty = Object.keys(draft).length

  const isSearching = search.trim() !== ''
  const searchResults = useMemo(
    () => (isSearching ? searchFields(view.fields, search, t) : []),
    [isSearching, view.fields, search, t],
  )

  const groupItems = useMemo(
    () => groupFields(view.fields, activeGroup),
    [view.fields, activeGroup],
  )

  // In Advanced group, user can filter by legacy section
  const advancedSections = useMemo(() => {
    const set = new Set<string>()
    for (const f of view.fields) {
      if (!f.honoured) set.add(f.section)
    }
    return Array.from(set)
  }, [view.fields])

  const displayedFields = useMemo(() => {
    if (isSearching) return searchResults
    if (activeGroup === 'advanced' && legacyFilter !== 'all') {
      return groupItems.filter((f) => f.section === legacyFilter)
    }
    return groupItems
  }, [isSearching, searchResults, activeGroup, legacyFilter, groupItems])

  const dirtyInGroup = (groupId: ConfigGroupId) => {
    const fieldsInGroup = groupFields(view.fields, groupId)
    return fieldsInGroup.filter((f) => f.key in draft).length
  }

  const submit = async () => {
    setErrors({})
    try {
      await save.mutateAsync(draft)
      setDraft({})
      toast.success(t('config.saved'))
    } catch (e) {
      if (isApiError(e) && Object.keys(e.fields).length > 0) {
        setErrors(e.fields)
      }
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const currentGroupMeta = CONFIG_GROUPS.find((g) => g.id === activeGroup)

  return (
    <div className="space-y-4">
      {/* Search box across all groups */}
      <div className="relative max-w-md">
        <Search
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('settingsUI.config.searchPlaceholder')}
          className="pl-9 pr-8"
        />
        {search && (
          <button
            type="button"
            onClick={() => setSearch('')}
            className="absolute top-1/2 right-2.5 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label={t('settingsUI.config.clearSearch')}
          >
            <X className="size-4" />
          </button>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[15rem_1fr]">
        {/* Navigation by 5 groups + Advanced */}
        <nav
          aria-label={t('config.sections')}
          className="flex flex-row flex-wrap gap-1 lg:flex-col"
        >
          {CONFIG_GROUPS.map((grp) => {
            const count = dirtyInGroup(grp.id)
            const Icon = GROUP_ICONS[grp.id]
            const active = !isSearching && grp.id === activeGroup
            return (
              <button
                key={grp.id}
                type="button"
                aria-current={active ? 'page' : undefined}
                onClick={() => {
                  setActiveGroup(grp.id)
                  setSearch('')
                }}
                className={cn(
                  'flex h-9 items-center justify-between gap-2 rounded-sm px-3 text-left text-body font-medium text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring',
                  active && 'bg-accent text-accent-foreground font-semibold',
                )}
              >
                <span className="flex items-center gap-2 truncate">
                  <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <span className="truncate">{t(grp.labelKey)}</span>
                </span>
                {count > 0 && (
                  <span
                    className="flex size-5 items-center justify-center rounded-full bg-primary text-micro text-primary-foreground font-semibold"
                    aria-label={t('config.modified')}
                  >
                    {count}
                  </span>
                )}
              </button>
            )
          })}
        </nav>

        {/* Content pane */}
        <section aria-labelledby="config-group-title" className="min-w-0 space-y-4">
          <div className="space-y-1">
            <h2 id="config-group-title" className="text-title font-semibold tracking-tight">
              {isSearching
                ? t('settingsUI.config.searchResultsCount', { count: searchResults.length })
                : t(currentGroupMeta?.labelKey ?? '')}
            </h2>
            <p className="text-body text-muted-foreground">
              {isSearching
                ? `${searchResults.length} settings match "${search}"`
                : t(currentGroupMeta?.helpKey ?? '')}
            </p>
          </div>

          {/* Legacy section filter in Advanced group */}
          {!isSearching && activeGroup === 'advanced' && (
            <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 p-2.5">
              <span className="text-caption font-medium text-muted-foreground">
                {t('settingsUI.config.filterBySection')}:
              </span>
              <button
                type="button"
                onClick={() => setLegacyFilter('all')}
                className={cn(
                  'rounded px-2 py-1 text-caption font-medium transition-colors',
                  legacyFilter === 'all'
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-card text-muted-foreground hover:text-foreground border',
                )}
              >
                {t('settingsUI.config.allGroups')}
              </button>
              {advancedSections.map((sec) => (
                <button
                  key={sec}
                  type="button"
                  onClick={() => setLegacyFilter(sec)}
                  className={cn(
                    'rounded px-2 py-1 text-caption font-medium transition-colors border',
                    legacyFilter === sec
                      ? 'bg-primary text-primary-foreground border-primary'
                      : 'bg-card text-muted-foreground hover:text-foreground',
                  )}
                >
                  {t(`config.section.${sec}`, { defaultValue: sec })}
                </button>
              ))}
            </div>
          )}

          {/* Triggers editor under Automation when not searching */}
          {!isSearching && activeGroup === 'automation' ? (
            <div className="space-y-6">
              <HooksSection />
              {groupItems.length > 0 && (
                <div className="rounded-md border bg-card px-4">
                  {groupItems.map((f) => (
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
            </div>
          ) : displayedFields.length === 0 ? (
            <EmptyState
              icon={<Search className="size-6 text-muted-foreground" aria-hidden />}
              title={t('settingsUI.config.noSearchResults')}
              action={
                isSearching ? (
                  <Button variant="outline" size="sm" onClick={() => setSearch('')}>
                    {t('settingsUI.config.clearSearch')}
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <div className="rounded-md border bg-card px-4">
              {displayedFields.map((f) => (
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

          {/* Sticky save bar */}
          <div className="sticky bottom-0 z-20 flex items-center justify-between gap-3 border-t bg-card/95 px-4 py-3 shadow-sm backdrop-blur">
            <div className="flex items-center gap-2">
              {readOnly ? (
                <p className="flex items-center gap-1.5 text-small text-muted-foreground">
                  <Lock className="size-4" aria-hidden />
                  {t('settingsUI.config.readOnlyNotice')}
                </p>
              ) : (
                <p className="text-small font-medium text-foreground" aria-live="polite">
                  {dirty > 0
                    ? t('settingsUI.config.unsavedChanges', { count: dirty })
                    : t('config.noChanges')}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={dirty === 0 || save.isPending}
                onClick={() => {
                  setDraft({})
                  setErrors({})
                }}
              >
                <Undo2 className="size-4" />
                {t('settingsUI.config.discard')}
              </Button>
              <Button
                size="sm"
                disabled={readOnly || dirty === 0 || save.isPending}
                onClick={() => void submit()}
              >
                <Save className="size-4" />
                {t('settingsUI.config.save')}
              </Button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}

export function ConfigPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = useConfig()
  return (
    <div className="space-y-4">
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

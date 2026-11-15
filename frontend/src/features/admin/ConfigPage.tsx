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
import { useQueryClient } from '@tanstack/react-query'
import { useBlocker } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { qk } from '@/api/hooks'
import { ErrorState } from '@/components/ErrorState'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageLayout } from '@/components/patterns'
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
  bySection,
  CONFIG_GROUPS,
  type ConfigGroupId,
  fromLines,
  groupFields,
  groupOfField,
  nextDraft,
  normalise,
  searchFields,
  toLines,
  validateDraft,
} from './configModel'
import { HooksSection } from './HooksSection'
import { useConfig, useSaveConfig } from './hooks'
import type { ConfigField, ConfigValue, ConfigView } from './types'
import '@/locales/settings.register'

const UNSET = '__unset__'

const GROUP_ICONS: Record<ConfigGroupId, typeof Settings2> = {
  general: Settings2,
  security: ShieldCheck,
  passwords: KeyRound,
  notifications: Bell,
  automation: Cpu,
  advanced: Layers,
}

/** DOM id of a setting's control (the screen shows each key once). */
const controlId = (key: string) => `config-${key}`

function FieldControl({
  field,
  value,
  readOnly,
  error,
  showStored,
  onChange,
  onTouch,
}: {
  field: ConfigField
  value: ConfigValue
  readOnly: boolean
  error?: string
  /** Mark the setting as stored for compatibility (the Advanced list says it once instead). */
  showStored: boolean
  onChange: (v: ConfigValue) => void
  onTouch: () => void
}) {
  const { t } = useTranslation()
  const technical = useTechnicalDetails()
  const id = controlId(field.key)
  const errorId = `${id}-error`
  const label = t(`config.field.${field.key}`)
  const helpText = t(`settingsUI.config.help.${field.key}`)
  const disabled = readOnly || field.hidden
  const invalid = !!error
  const describedBy = [error ? errorId : null, field.kind === 'list' ? `${id}-hint` : null]
    .filter(Boolean)
    .join(' ')
  const optionLabel = (o: string) => t(`config.option.${o}`, { defaultValue: o })

  let control: React.ReactNode
  switch (field.kind) {
    case 'bool':
      control = (
        <Switch
          id={id}
          checked={value === true}
          disabled={disabled}
          onCheckedChange={onChange}
          aria-invalid={invalid}
          aria-describedby={describedBy || undefined}
        />
      )
      break
    case 'int':
      control = (
        <Input
          id={id}
          type="number"
          min={field.constraints?.min ?? 0}
          max={field.constraints?.max}
          step={1}
          className="max-w-40 tabular-nums"
          value={typeof value === 'number' ? String(value) : ''}
          disabled={disabled}
          aria-invalid={invalid}
          aria-describedby={describedBy || undefined}
          onChange={(e) => {
            const n = e.target.value === '' ? null : Number(e.target.value)
            onChange(n !== null && Number.isNaN(n) ? null : n)
          }}
        />
      )
      break
    case 'select': {
      const current = typeof value === 'string' ? value : ''
      // a stored value the server no longer offers stays visible until the user picks another
      const choices =
        current !== '' && !field.options.includes(current)
          ? [...field.options, current]
          : field.options
      control = (
        <Select
          value={current !== '' ? current : UNSET}
          disabled={disabled}
          onValueChange={(v) => onChange(v === UNSET ? '' : v)}
        >
          <SelectTrigger
            id={id}
            className="w-full max-w-64"
            aria-invalid={invalid}
            aria-describedby={describedBy || undefined}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={UNSET}>{t('config.unset')}</SelectItem>
            {choices.map((o) => (
              <SelectItem key={o} value={o}>
                {optionLabel(o)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )
      break
    }
    case 'list':
      if (field.options.length > 0) {
        const selected = Array.isArray(value) ? value : []
        const choices = [...field.options, ...selected.filter((v) => !field.options.includes(v))]
        control = (
          <div
            id={id}
            role="group"
            tabIndex={-1}
            aria-labelledby={`${id}-label`}
            aria-invalid={invalid}
            aria-describedby={describedBy || undefined}
            className="flex flex-wrap gap-x-5 gap-y-2 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {choices.map((o) => (
              <label key={o} className="flex items-center gap-2 text-body">
                <Checkbox
                  checked={selected.includes(o)}
                  disabled={disabled}
                  onCheckedChange={(on) =>
                    onChange(choices.filter((c) => (c === o ? on === true : selected.includes(c))))
                  }
                />
                <span className="font-mono text-xs">{optionLabel(o)}</span>
              </label>
            ))}
          </div>
        )
        break
      }
      control = (
        <Textarea
          id={id}
          rows={3}
          className="font-mono text-xs"
          value={toLines(value)}
          disabled={disabled}
          aria-invalid={invalid}
          aria-describedby={describedBy || undefined}
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
          aria-invalid={invalid}
          aria-describedby={describedBy || undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      )
      break
    default:
      control = (
        <Input
          id={id}
          // a secret is never shown on screen, not even to the people allowed to change it
          type={field.secret ? 'password' : 'text'}
          autoComplete={field.secret ? 'new-password' : 'off'}
          className={cn(field.kind === 'path' && 'font-mono text-xs')}
          value={field.hidden ? '' : typeof value === 'string' ? value : ''}
          placeholder={field.hidden ? t('config.hidden') : undefined}
          disabled={disabled}
          aria-invalid={invalid}
          aria-describedby={describedBy || undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      )
  }

  return (
    <div className="grid gap-1.5 border-b border-border py-3 last:border-b-0 md:grid-cols-[minmax(0,18rem)_1fr] md:gap-6">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <Label htmlFor={id} id={`${id}-label`} className="leading-snug font-medium">
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
          <p className="text-caption text-muted-foreground leading-normal">{helpText}</p>
        )}
        {showStored && !field.honoured && (
          <div>
            <Badge variant="neutral" title={t('settingsUI.config.storedNotice')}>
              {t('settingsUI.config.storedBadge')}
            </Badge>
          </div>
        )}
      </div>
      <div className="min-w-0 space-y-1" onBlur={onTouch}>
        {control}
        {field.kind === 'list' && field.options.length === 0 && (
          <p id={`${id}-hint`} className="text-caption text-muted-foreground">
            {t('config.listHint')}
          </p>
        )}
        {error && (
          <p id={errorId} role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}

function ConfigEditor({ view }: { view: ConfigView }) {
  const { t, i18n } = useTranslation()
  const save = useSaveConfig()
  const qc = useQueryClient()
  const [activeGroup, setActiveGroup] = useState<ConfigGroupId>('general')
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState<Record<string, ConfigValue>>({})
  /** Messages of the last refused save, by key (a key is cleared when its value changes). */
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({})
  /** Settings the user has left once: their client-side error is shown from then on. */
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set())
  const [attempted, setAttempted] = useState(false)
  const pendingFocus = useRef<string | null>(null)
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

  const displayedFields = isSearching ? searchResults : groupItems

  const fieldByKey = useMemo(() => new Map(view.fields.map((f) => [f.key, f])), [view.fields])

  // what the server would refuse; recomputed when the language changes (the messages are translated)
  const clientErrors = useMemo(
    () => validateDraft(view.fields, draft),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [view.fields, draft, i18n.language],
  )
  const allErrors = useMemo(() => ({ ...serverErrors, ...clientErrors }), [serverErrors, clientErrors])
  const clientErrorCount = Object.keys(clientErrors).length
  const errorCount = Object.keys(allErrors).length

  const errorsByGroup = useMemo(() => {
    const counts: Partial<Record<ConfigGroupId, number>> = {}
    for (const key of Object.keys(allErrors)) {
      const f = fieldByKey.get(key)
      if (!f) continue
      const g = groupOfField(f)
      counts[g] = (counts[g] ?? 0) + 1
    }
    return counts
  }, [allErrors, fieldByKey])

  const shownError = (key: string): string | undefined =>
    key in serverErrors
      ? serverErrors[key]
      : touched.has(key) || attempted
        ? clientErrors[key]
        : undefined

  const dirtyInGroup = (groupId: ConfigGroupId) =>
    groupFields(view.fields, groupId).filter((f) => f.key in draft).length

  // Leaving with unsaved changes asks first (also covers closing the tab).
  const blocker = useBlocker({
    shouldBlockFn: () => dirty > 0,
    withResolver: true,
    enableBeforeUnload: () => dirty > 0,
  })

  // Focus a setting once the group that holds it is on screen.
  useEffect(() => {
    const key = pendingFocus.current
    if (!key) return
    const el = document.getElementById(controlId(key))
    if (el) {
      pendingFocus.current = null
      el.focus()
    }
  })

  /** Switch to the group of a setting and put the focus on it. */
  const goTo = (key: string) => {
    const f = fieldByKey.get(key)
    if (!f) return
    setSearch('')
    setActiveGroup(groupOfField(f))
    pendingFocus.current = key
    const el = document.getElementById(controlId(key))
    if (el) {
      pendingFocus.current = null
      el.focus()
    }
  }

  const touch = (key: string) => setTouched((s) => (s.has(key) ? s : new Set(s).add(key)))

  const change = (f: ConfigField, v: ConfigValue) => {
    setDraft((d) => nextDraft(d, f, v))
    setServerErrors((s) => {
      if (!(f.key in s)) return s
      const next = { ...s }
      delete next[f.key]
      return next
    })
    // choices cannot be half-typed: their error shows at once
    if (f.kind === 'bool' || f.kind === 'select' || f.options.length > 0) touch(f.key)
  }

  const reset = () => {
    setDraft({})
    setServerErrors({})
    setTouched(new Set())
    setAttempted(false)
  }

  const firstErrorKey = () => view.fields.find((f) => f.key in allErrors)?.key

  const showErrors = () => {
    setAttempted(true)
    const key = firstErrorKey()
    if (key) goTo(key)
  }

  const submit = async () => {
    if (clientErrorCount > 0) {
      showErrors()
      return
    }
    setServerErrors({})
    try {
      await save.mutateAsync(draft)
      reset()
      // mail_domain reaches the create-user wizard through /auth/me
      void qc.invalidateQueries({ queryKey: qk.me })
      toast.success(t('config.saved'))
    } catch (e) {
      const fields = isApiError(e) ? e.fields : {}
      const keys = Object.keys(fields)
      if (keys.length > 0) {
        setServerErrors(fields)
        setAttempted(true)
        const first = keys.find((k) => fieldByKey.has(k))
        if (first) goTo(first)
        const orphans = keys.filter((k) => !fieldByKey.has(k)).map((k) => fields[k])
        if (orphans.length > 0) toast.error(orphans.join(' '))
      } else {
        toast.error(isApiError(e) ? e.message : t('common.error'))
      }
    }
  }

  const currentGroupMeta = CONFIG_GROUPS.find((g) => g.id === activeGroup)
  const inAdvanced = !isSearching && activeGroup === 'advanced'

  const row = (f: ConfigField) => (
    <FieldControl
      key={f.key}
      field={f}
      value={f.key in draft ? (draft[f.key] ?? null) : normalise(f, f.value)}
      readOnly={readOnly}
      error={shownError(f.key)}
      showStored={!inAdvanced}
      onChange={(v) => change(f, v)}
      onTouch={() => touch(f.key)}
    />
  )

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
            const invalidCount = errorsByGroup[grp.id] ?? 0
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
                <span className="flex items-center gap-1">
                  {invalidCount > 0 && (
                    <span
                      className="flex size-5 items-center justify-center rounded-full bg-destructive text-micro text-white font-semibold"
                      aria-label={t('settingsUI.config.invalidInGroup', { count: invalidCount })}
                    >
                      {invalidCount}
                    </span>
                  )}
                  {count > 0 && (
                    <span
                      className="flex size-5 items-center justify-center rounded-full bg-primary text-micro text-primary-foreground font-semibold"
                      aria-label={t('config.modified')}
                    >
                      {count}
                    </span>
                  )}
                </span>
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
                ? t('config.searchHint', { query: search.trim() })
                : t(currentGroupMeta?.helpKey ?? '')}
            </p>
          </div>

          {/* What "stored for compatibility" means, said once for the whole list */}
          {inAdvanced && (
            <p className="rounded-md border bg-muted/30 px-3 py-2 text-caption text-muted-foreground">
              {t('config.storedGroupNotice')}
            </p>
          )}

          {/* Triggers editor under Automation when not searching */}
          {!isSearching && activeGroup === 'automation' ? (
            <div className="space-y-6">
              <HooksSection />
              {groupItems.length > 0 && (
                <div className="rounded-md border bg-card px-4">{groupItems.map(row)}</div>
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
          ) : inAdvanced ? (
            <div className="space-y-5">
              {bySection(groupItems, view.sections).map((s) => (
                <div key={s.section} className="space-y-2">
                  <h3 className="text-small font-semibold text-foreground">
                    {t(`config.section.${s.section}`)}
                  </h3>
                  <div className="rounded-md border bg-card px-4">{s.fields.map(row)}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-md border bg-card px-4">{displayedFields.map(row)}</div>
          )}

          {/* Sticky save bar */}
          <div className="sticky bottom-0 z-20 flex items-center justify-between gap-3 border-t bg-card/95 px-4 py-3 shadow-sm backdrop-blur">
            <div className="flex items-center gap-2">
              {readOnly ? (
                <p className="flex items-center gap-1.5 text-small text-muted-foreground">
                  <Lock className="size-4" aria-hidden />
                  {t('settingsUI.config.readOnlyNotice')}
                </p>
              ) : errorCount > 0 ? (
                <p
                  className="flex flex-wrap items-center gap-x-2 text-small font-medium text-destructive"
                  aria-live="polite"
                >
                  {t('settingsUI.config.needFixing', { count: errorCount })}
                  <Button
                    type="button"
                    variant="link"
                    size="sm"
                    className="h-auto p-0 text-small"
                    onClick={showErrors}
                  >
                    {t('config.showFirstError')}
                  </Button>
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
                onClick={reset}
              >
                <Undo2 className="size-4" />
                {t('settingsUI.config.discard')}
              </Button>
              <Button
                size="sm"
                disabled={readOnly || dirty === 0 || save.isPending || clientErrorCount > 0}
                onClick={() => void submit()}
              >
                <Save className="size-4" />
                {t('settingsUI.config.save')}
              </Button>
            </div>
          </div>
        </section>
      </div>

      <AlertDialog open={blocker.status === 'blocked'}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lead font-semibold">
              {t('editor.leaveTitle')}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-body text-muted-foreground">
              {t('editor.leaveBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.status === 'blocked' && blocker.reset()}>
              {t('editor.stay')}
            </AlertDialogCancel>
            <AlertDialogAction onClick={() => blocker.status === 'blocked' && blocker.proceed()}>
              {t('editor.leave')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

export function ConfigPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = useConfig()
  return (
    <PageLayout title={t('config.title')} description={t('config.description')}>
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
    </PageLayout>
  )
}

import { ChevronDown, ChevronRight, Download, ScrollText, X } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useTypes } from '@/api/hooks'
import { ErrorState } from '@/components/ErrorState'
import { ObjectRefPicker } from '@/components/fields/RefFields'
import { FilterBar, FilterChip } from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { PageLayout } from '@/components/patterns'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { typeLabel } from '@/lib/labels'
import { rdnValue } from '@/lib/objects'
import { auditApi } from './api'
import { ActionBadge, ActorChip, AttributeDiff, ObjectCell, WhenCell } from './EventParts'
import { AUDIT_TYPE, useAuditEnabled, useAuditEvents } from './hooks'
import { AUDIT_ACTIONS, type AuditFilters } from './types'

type Preset = '24h' | '7d' | '30d' | 'custom'

const PRESET_HOURS: Record<Exclude<Preset, 'custom'>, number> = { '24h': 24, '7d': 7 * 24, '30d': 30 * 24 }

export interface AuditPageProps {
  /** Start with the log narrowed to this object (and what is below it). */
  object?: string
  /** Start with the log narrowed to the events made by this person. */
  actor?: string
}

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

/** The audit log: filters on top, newest events first, changes expandable. */
export function AuditPage({ object: initialObject = '', actor: initialActor = '' }: AuditPageProps) {
  const { t } = useTranslation()
  const { enabled, pending } = useAuditEnabled()
  const types = useTypes()

  const [preset, setPreset] = useState<Preset>('7d')
  // The window is anchored when a preset is picked, so the query key stays stable between renders.
  const [anchor, setAnchor] = useState(() => Date.now())
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [actor, setActor] = useState(initialActor)
  const [object, setObject] = useState(initialObject)
  const [actions, setActions] = useState<string[]>([])
  const [objectTypes, setObjectTypes] = useState<string[]>([])
  const [results, setResults] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const q = useDebounced(search.trim())
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const filters = useMemo<AuditFilters>(() => {
    const f: AuditFilters = { limit: 50 }
    if (preset === 'custom') {
      if (customFrom) f.from = customFrom
      if (customTo) f.to = customTo
    } else {
      f.from = new Date(anchor - PRESET_HOURS[preset] * 3600_000).toISOString()
    }
    if (actor) f.actor = actor
    if (object) f.object = object
    if (actions.length > 0) f.action = actions
    if (objectTypes.length === 1) f.type = objectTypes[0]
    if (results.length === 1) f.result = results[0]
    if (q) f.q = q
    return f
  }, [preset, anchor, customFrom, customTo, actor, object, actions, objectTypes, results, q])

  const list = useAuditEvents(filters, enabled)
  const events = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data])
  // Several object types are filtered client-side: the endpoint takes one.
  const rows = useMemo(
    () => (objectTypes.length > 1 ? events.filter((e) => objectTypes.includes(e.object.type)) : events),
    [events, objectTypes],
  )

  const hasFilters =
    Boolean(actor || object || q) || actions.length > 0 || objectTypes.length > 0 || results.length > 0

  const clearFilters = () => {
    setActor('')
    setObject('')
    setActions([])
    setObjectTypes([])
    setResults([])
    setSearch('')
  }

  const toggle = (dn: string) =>
    setExpanded((cur) => {
      const next = new Set(cur)
      if (next.has(dn)) next.delete(dn)
      else next.add(dn)
      return next
    })

  if (!pending && !enabled) {
    return (
      <div className="mx-auto max-w-md">
        <EmptyState
          icon={<ScrollText aria-hidden />}
          title={t('audit.notEnabled.title')}
          description={t('audit.notEnabled.description')}
          action={
            <Button asChild size="sm">
              <Link to="/admin/plugins">{t('onboarding.next.plugins')}</Link>
            </Button>
          }
        />
      </div>
    )
  }

  const typeOptions = (types.data ?? [])
    .filter((x) => x.name !== AUDIT_TYPE)
    .map((x) => ({ value: x.name, label: typeLabel(t, x) }))

  return (
    <PageLayout
        title={t('audit.title')}
        description={t('audit.description')}
        actions={
          <Button asChild variant="outline" size="sm">
            <a href={auditApi.exportUrl(filters)} download="audit-log.csv">
              <Download aria-hidden />
              {t('audit.exportCsv')}
            </a>
          </Button>
        }
      >
      <FilterBar search={search} onSearch={setSearch} placeholder={t('audit.search')}>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={preset}
          onValueChange={(v) => {
            if (v === '24h' || v === '7d' || v === '30d' || v === 'custom') {
              setPreset(v)
              setAnchor(Date.now())
            }
          }}
          aria-label={t('audit.period')}
        >
          <ToggleGroupItem value="24h">{t('audit.range.h24')}</ToggleGroupItem>
          <ToggleGroupItem value="7d">{t('audit.range.d7')}</ToggleGroupItem>
          <ToggleGroupItem value="30d">{t('audit.range.d30')}</ToggleGroupItem>
          <ToggleGroupItem value="custom">{t('audit.range.custom')}</ToggleGroupItem>
        </ToggleGroup>
        {preset === 'custom' && (
          <>
            <label className="flex items-center gap-1.5 text-small text-muted-foreground">
              {t('audit.from')}
              <Input
                type="date"
                value={customFrom}
                max={customTo || undefined}
                onChange={(e) => setCustomFrom(e.target.value)}
                className="h-8 w-36"
              />
            </label>
            <label className="flex items-center gap-1.5 text-small text-muted-foreground">
              {t('audit.to')}
              <Input
                type="date"
                value={customTo}
                min={customFrom || undefined}
                onChange={(e) => setCustomTo(e.target.value)}
                className="h-8 w-36"
              />
            </label>
          </>
        )}
        <FilterChip
          label={t('audit.filters.action')}
          options={AUDIT_ACTIONS.map((a) => ({ value: a, label: t(`audit.actions.${a}`) }))}
          selected={actions}
          onChange={setActions}
        />
        <FilterChip
          label={t('audit.filters.type')}
          options={typeOptions}
          selected={objectTypes}
          onChange={setObjectTypes}
        />
        <FilterChip
          label={t('audit.filters.result')}
          options={[
            { value: 'success', label: t('audit.results.success') },
            { value: 'failure', label: t('audit.results.failure') },
          ]}
          selected={results}
          onChange={(v) => setResults(v.length === 2 ? [] : v)}
        />
        <div className="w-52">
          {actor ? (
            <span className="inline-flex h-8 w-full items-center justify-between gap-1 rounded-md border border-primary/40 bg-primary-soft px-2 text-small">
              <span className="truncate" title={actor}>
                {t('audit.filters.actor')}: {rdnValue(actor)}
              </span>
              <button
                type="button"
                onClick={() => setActor('')}
                aria-label={t('audit.actor.clear')}
                className="rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            </span>
          ) : (
            <ObjectRefPicker
              id="audit-actor"
              refType="user"
              label={t('audit.actor.pick')}
              selected={[]}
              onPick={setActor}
            />
          )}
        </div>
        {object && (
          <span className="inline-flex h-8 max-w-72 items-center gap-1 rounded-md border border-primary/40 bg-primary-soft px-2 text-small">
            <span className="truncate" title={object}>
              {t('audit.object.filter')}: {rdnValue(object)}
            </span>
            <button
              type="button"
              onClick={() => setObject('')}
              aria-label={t('audit.object.clear')}
              className="rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
            >
              <X className="size-3.5" />
            </button>
          </span>
        )}
        {hasFilters && (
          <Button type="button" variant="ghost" size="sm" onClick={clearFilters}>
            {t('audit.filters.clear')}
          </Button>
        )}
      </FilterBar>

      {list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.isPending ? (
        <div className="space-y-2" aria-busy="true" aria-label={t('common.loading')}>
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<ScrollText aria-hidden />}
          title={t('audit.empty.title')}
          description={t('audit.empty.description')}
          action={
            hasFilters ? (
              <Button variant="outline" size="sm" onClick={clearFilters}>
                {t('audit.filters.clear')}
              </Button>
            ) : (
              <Button asChild variant="outline" size="sm">
                <Link to="/types/$type" params={{ type: 'user' }}>
                  {t('onboarding.next.people')}
                </Link>
              </Button>
            )
          }
        />
      ) : (
        <div className="overflow-hidden rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>{t('audit.columns.time')}</TableHead>
                <TableHead>{t('audit.columns.actor')}</TableHead>
                <TableHead>{t('audit.columns.action')}</TableHead>
                <TableHead>{t('audit.columns.object')}</TableHead>
                <TableHead>{t('audit.columns.address')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((e) => {
                const open = expanded.has(e.dn)
                const hasDetails = e.attributes.length > 0
                return (
                  <Fragment key={e.dn}>
                    <TableRow data-testid="audit-row">
                      <TableCell className="align-top">
                        {hasDetails && (
                          <button
                            type="button"
                            onClick={() => toggle(e.dn)}
                            aria-expanded={open}
                            aria-label={open ? t('audit.details.hide') : t('audit.details.show')}
                            className="rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
                          >
                            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                          </button>
                        )}
                      </TableCell>
                      <TableCell className="align-top">
                        <WhenCell iso={e.time} />
                      </TableCell>
                      <TableCell className="max-w-64 align-top">
                        <ActorChip actor={e.actor} />
                      </TableCell>
                      <TableCell className="align-top">
                        <ActionBadge event={e} />
                      </TableCell>
                      <TableCell className="max-w-96 align-top">
                        <ObjectCell event={e} />
                      </TableCell>
                      <TableCell className="align-top font-dn text-caption text-muted-foreground">
                        {e.ip || '—'}
                      </TableCell>
                    </TableRow>
                    {open && (
                      <TableRow className="bg-muted/30 hover:bg-muted/30">
                        <TableCell />
                        <TableCell colSpan={5}>
                          <AttributeDiff lines={e.attributes} />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                )
              })}
            </TableBody>
          </Table>
          {list.hasNextPage && (
            <div className="border-t p-3 text-center">
              <Button
                variant="outline"
                size="sm"
                disabled={list.isFetchingNextPage}
                onClick={() => void list.fetchNextPage()}
              >
                {t('audit.loadMore')}
              </Button>
            </div>
          )}
        </div>
      )}
    </PageLayout>
  )
}

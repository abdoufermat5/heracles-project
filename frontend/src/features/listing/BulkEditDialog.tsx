import { Check, Plus, Trash2, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import type { AttributeDescriptor, TypeDescriptor } from '@/api/types'
import { FieldInput } from '@/components/fields/FieldInput'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useBulkAttributes,
  useBulkEdit,
  type BulkChange,
  type BulkChanges,
  type BulkResult,
} from '@/features/editor/api'
import { defaultValue, rdnValue } from '@/lib/objects'
import { ErrorState } from '@/components/ErrorState'

type Op = BulkChange['op']

interface Choice {
  key: string
  tab: string
  tabLabel: string
  attr: AttributeDescriptor
}

interface Row {
  id: number
  key: string
  op: Op
  value: unknown
}

function formatChange(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** Whether an attribute holds several values (so add / remove make sense). */
function holdsSeveral(a: AttributeDescriptor): boolean {
  return a.kind === 'list' || a.kind === 'multiselect' || a.multivalued === true
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  type: string
  descriptor: TypeDescriptor | undefined
  dns: string[]
}

/** Multiple edit: the same change applied to every selected object, with per-object results. */
export function BulkEditDialog(props: Props) {
  return props.open ? <Inner {...props} /> : null
}

function Inner({ onOpenChange, type, descriptor, dns }: Props) {
  const { t } = useTranslation()
  const available = useBulkAttributes(type, dns, true)
  const edit = useBulkEdit(type)
  const [rows, setRows] = useState<Row[]>([])
  const [nextId, setNextId] = useState(1)
  const [results, setResults] = useState<BulkResult[] | null>(null)
  // Step two: the exact objects and attribute changes, before anything is written.
  const [reviewing, setReviewing] = useState(false)

  const choices = useMemo<Choice[]>(() => {
    const out: Choice[] = []
    for (const tab of descriptor?.tabs ?? []) {
      const names = new Set(available.data?.attributes[tab.name] ?? [])
      for (const sec of tab.sections) {
        for (const attr of sec.attributes) {
          if (names.has(attr.name)) {
            out.push({ key: `${tab.name}.${attr.name}`, tab: tab.name, tabLabel: tab.label, attr })
          }
        }
      }
    }
    return out
  }, [descriptor, available.data])

  const byKey = (key: string) => choices.find((c) => c.key === key)
  const used = new Set(rows.map((r) => r.key))

  const update = (id: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)))

  const addRow = () => {
    setRows((rs) => [...rs, { id: nextId, key: '', op: 'set', value: null }])
    setNextId((n) => n + 1)
  }

  const pick = (id: number, key: string) => {
    const choice = byKey(key)
    update(id, { key, op: 'set', value: choice ? defaultValue(choice.attr) : null })
  }

  const apply = async () => {
    const changes: BulkChanges = {}
    for (const r of rows) {
      const choice = byKey(r.key)
      if (!choice) continue
      const tabChanges = (changes[choice.tab] ??= {})
      tabChanges[choice.attr.name] = r.op === 'clear' ? { op: 'clear' } : { op: r.op, value: r.value }
    }
    if (Object.keys(changes).length === 0) return
    try {
      const res = await edit.mutateAsync({ dns, changes })
      setResults(res.results)
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const failed = results?.filter((r) => !r.ok).length ?? 0
  const okCount = (results?.length ?? 0) - failed
  const ready = rows.some((r) => byKey(r.key))

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-lead">{t('bulkEdit.title', { count: dns.length })}</DialogTitle>
          <DialogDescription className="text-body">{t('bulkEdit.help')}</DialogDescription>
        </DialogHeader>

        {results !== null ? (
          <div className="space-y-3">
            <p role="status" className="text-body font-medium text-foreground">
              {failed === 0
                ? t('bulkEdit.allOk', { count: okCount })
                : t('bulkEdit.partial', { ok: okCount, failed })}
            </p>
            <ul className="max-h-72 space-y-1.5 overflow-y-auto text-body" aria-label={t('bulkEdit.results')}>
              {results.map((r) => (
                <li key={r.dn} className="flex items-start gap-2">
                  {r.ok ? (
                    <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />
                  ) : (
                    <X className="mt-0.5 size-3.5 shrink-0 text-destructive" aria-hidden />
                  )}
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-foreground" title={r.dn}>
                      {rdnValue(r.dn)}
                    </span>
                    {r.ok ? (
                      <span className="text-xs text-muted-foreground">{t('bulkEdit.status_ok')}</span>
                    ) : (
                      <span className="text-xs text-destructive">
                        {[r.error, ...Object.values(r.fields ?? {})].filter(Boolean).join(' — ')}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : reviewing ? (
          <div className="space-y-3" data-testid="bulk-review">
            <p className="text-body font-medium text-foreground">
              {t('safety.bulkObjects', { count: dns.length })}
            </p>
            <ul
              className="max-h-32 overflow-y-auto rounded-md border bg-muted/40 p-2 font-mono text-small"
              aria-label={t('safety.bulkObjectsList')}
            >
              {dns.map((dn) => (
                <li key={dn} className="truncate" title={dn}>
                  {dn}
                </li>
              ))}
            </ul>
            <p className="text-small font-semibold tracking-wide text-muted-foreground uppercase">
              {t('safety.bulkChanges')}
            </p>
            <ul className="max-h-40 divide-y overflow-y-auto rounded-md border">
              {rows.flatMap((r) => {
                const choice = byKey(r.key)
                if (!choice) return []
                return [
                  <li key={r.id} className="flex flex-wrap items-baseline gap-x-2 px-3 py-2">
                    <span className="text-body font-medium">{choice.attr.label}</span>
                    <span className="font-mono text-caption text-muted-foreground">
                      {choice.attr.name}
                    </span>
                    <span className="text-caption text-muted-foreground">
                      {t(`bulkEdit.op_${r.op}`)}
                    </span>
                    {r.op !== 'clear' && (
                      <span className="font-mono text-small break-all text-success">
                        {formatChange(r.value)}
                      </span>
                    )}
                  </li>,
                ]
              })}
            </ul>
          </div>
        ) : available.isError ? (
          <ErrorState error={available.error} onRetry={() => void available.refetch()} />
        ) : !available.data ? (
          <div className="space-y-2" aria-busy="true" aria-label={t('common.loading')}>
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-2/3" />
          </div>
        ) : choices.length === 0 ? (
          <p className="rounded-md border border-dashed p-4 text-body text-muted-foreground">
            {t('bulkEdit.noAttributes')}
          </p>
        ) : (
          <div className="space-y-3">
            <ul className="max-h-80 space-y-3 overflow-y-auto pr-1">
              {rows.map((r, index) => {
                const choice = byKey(r.key)
                const ops: Op[] = choice && holdsSeveral(choice.attr) ? ['set', 'add', 'remove', 'clear'] : ['set', 'clear']
                return (
                  <li key={r.id} className="space-y-2 rounded-md border bg-card p-3">
                    <div className="grid grid-cols-[minmax(0,1fr)_10rem_auto] items-end gap-2">
                      <div className="space-y-1.5">
                        <Label htmlFor={`bulk-attr-${r.id}`} className="text-xs font-medium text-muted-foreground">
                          {t('bulkEdit.attribute')}
                        </Label>
                        <Select value={r.key} onValueChange={(v) => pick(r.id, v)}>
                          <SelectTrigger id={`bulk-attr-${r.id}`} className="h-8 text-body">
                            <SelectValue placeholder={t('bulkEdit.choose')} />
                          </SelectTrigger>
                          <SelectContent>
                            {choices
                              .filter((c) => c.key === r.key || !used.has(c.key))
                              .map((c) => (
                                <SelectItem key={c.key} value={c.key}>
                                  {c.attr.label}
                                </SelectItem>
                              ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor={`bulk-op-${r.id}`} className="text-xs font-medium text-muted-foreground">
                          {t('bulkEdit.operation')}
                        </Label>
                        <Select
                          value={r.op}
                          onValueChange={(v) => update(r.id, { op: v as Op })}
                          disabled={!choice}
                        >
                          <SelectTrigger id={`bulk-op-${r.id}`} className="h-8 text-body">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {ops.map((op) => (
                              <SelectItem key={op} value={op}>
                                {t(`bulkEdit.op_${op}`)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`${t('bulkEdit.removeChange')} ${index + 1}`}
                        onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}
                      >
                        <Trash2 aria-hidden />
                      </Button>
                    </div>
                    {choice && r.op !== 'clear' && (
                      <div className="space-y-1.5">
                        <Label htmlFor={`bulk-value-${r.id}`} className="text-xs font-medium text-muted-foreground">
                          {t('bulkEdit.value')}
                        </Label>
                        <FieldInput
                          descriptor={{ ...choice.attr, required: false, readonly: false }}
                          id={`bulk-value-${r.id}`}
                          value={r.value}
                          onChange={(v) => update(r.id, { value: v })}
                        />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addRow}
              disabled={rows.length >= choices.length}
            >
              <Plus aria-hidden />
              {t('bulkEdit.addChange')}
            </Button>
          </div>
        )}

        <DialogFooter>
          {results === null ? (
            <>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => (reviewing ? setReviewing(false) : onOpenChange(false))}
              >
                {reviewing ? t('safety.cancel') : t('common.cancel')}
              </Button>
              {reviewing ? (
                <Button type="button" size="sm" onClick={() => void apply()} disabled={edit.isPending}>
                  {edit.isPending ? t('bulkEdit.applying') : t('bulkEdit.apply')}
                </Button>
              ) : (
                <Button type="button" size="sm" onClick={() => setReviewing(true)} disabled={!ready}>
                  {t('safety.reviewBulk')}
                </Button>
              )}
            </>
          ) : (
            <Button type="button" size="sm" onClick={() => onOpenChange(false)}>
              {t('bulkEdit.close')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

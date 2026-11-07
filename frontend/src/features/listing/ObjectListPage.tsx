import { Link, useNavigate } from '@tanstack/react-router'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
  type SortingState,
} from '@tanstack/react-table'
import { observeElementRect, useVirtualizer } from '@tanstack/react-virtual'
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Inbox,
  Lock,
  LockOpen,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useAccountLock, useDeleteObjects, useMe, useObjectList, useTypeDescriptor, useTypes } from '@/api/hooks'
import type { ObjectListItem } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/ErrorState'
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
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useScope } from '@/lib/scope'
import { cn } from '@/lib/utils'

const ROW_HEIGHT = 44

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

function formatCell(v: unknown, yes: string, no: string): string {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'boolean') return v ? yes : no
  return String(v)
}

export function ObjectListPage({ type }: { type: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const desc = useTypeDescriptor(type)
  const types = useTypes()
  const me = useMe()
  const { base, scope, setScope } = useScope()

  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const [sorting, setSorting] = useState<SortingState>([])
  const [selection, setSelection] = useState<RowSelectionState>({})
  const [confirmDelete, setConfirmDelete] = useState(false)

  const sort = sorting[0]
  const list = useObjectList(type, {
    base: base ?? me.data?.base,
    scope,
    q: dq || undefined,
    sort: sort?.id,
    order: sort ? (sort.desc ? 'desc' : 'asc') : undefined,
    limit: 50,
  })

  const rows: ObjectListItem[] = useMemo(
    () => list.data?.pages.flatMap((p) => p.items) ?? [],
    [list.data],
  )
  const total = list.data?.pages[0]?.total ?? null
  const summary = types.data?.find((x) => x.name === type)
  const label = summary?.label_plural ?? desc.data?.label ?? type

  // selection is per query result set
  useEffect(() => setSelection({}), [type, base, scope, dq])

  const linkKey = desc.data?.main_attr ?? desc.data?.columns[0]?.key

  const columns = useMemo<ColumnDef<ObjectListItem>[]>(() => {
    if (!desc.data) return []
    const cols: ColumnDef<ObjectListItem>[] = [
      {
        id: 'select',
        enableSorting: false,
        header: ({ table }) => (
          <Checkbox
            checked={table.getIsAllRowsSelected() ? true : table.getIsSomeRowsSelected() ? 'indeterminate' : false}
            onCheckedChange={(v) => table.toggleAllRowsSelected(v === true)}
            aria-label={t('listing.selectAll')}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(v) => row.toggleSelected(v === true)}
            onClick={(e) => e.stopPropagation()}
            aria-label={t('listing.selectRow', { name: String(row.original.values[desc.data.name_attr] ?? row.original.dn) })}
          />
        ),
      },
      ...desc.data.columns.map<ColumnDef<ObjectListItem>>((c) => ({
        id: c.key,
        header: c.label,
        accessorFn: (r) => r.values[c.key],
        cell: ({ row, getValue }) => {
          const text = formatCell(getValue(), t('common.yes'), t('common.no'))
          if (c.key !== linkKey) return <span className="text-muted-foreground">{text}</span>
          return (
            <span className="flex items-center gap-2">
              <Link
                to="/types/$type/$dn"
                params={{ type, dn: row.original.dn }}
                className="hover:text-primary font-medium focus-visible:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {text}
              </Link>
              {row.original.locked && (
                <Badge variant="outline" className="text-warning border-warning/40 gap-1">
                  <Lock className="size-3" aria-hidden />
                  {t('listing.locked')}
                </Badge>
              )}
            </span>
          )
        },
      })),
    ]
    return cols
  }, [desc.data, linkKey, t, type])

  const table = useReactTable({
    data: rows,
    columns,
    getRowId: (r) => r.dn,
    getCoreRowModel: getCoreRowModel(),
    state: { sorting, rowSelection: selection },
    onSortingChange: setSorting,
    onRowSelectionChange: setSelection,
    manualSorting: true,
    enableSortingRemoval: true,
    enableMultiSort: false,
  })

  const tableRows = table.getRowModel().rows
  const scroller = useRef<HTMLDivElement>(null)
  const virtual = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    // A container that has no layout yet (hidden tab, test DOM) would render no
    // rows at all; assume a sensible viewport in that case.
    initialRect: { width: 800, height: 600 },
    observeElementRect: (instance, cb) =>
      observeElementRect(instance, (rect) =>
        cb(rect.height === 0 ? { width: rect.width, height: 600 } : rect),
      ),
  })
  const items = virtual.getVirtualItems()
  const lastIndex = items.length ? (items[items.length - 1]?.index ?? 0) : 0
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = list

  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && tableRows.length > 0 && lastIndex >= tableRows.length - 8) {
      void fetchNextPage()
    }
  }, [lastIndex, tableRows.length, hasNextPage, isFetchingNextPage, fetchNextPage])

  const padTop = items.length ? (items[0]?.start ?? 0) : 0
  const padBottom = items.length ? virtual.getTotalSize() - (items[items.length - 1]?.end ?? 0) : 0

  const selectedDns = Object.keys(selection).filter((k) => selection[k])
  const del = useDeleteObjects(type)
  const lock = useAccountLock(type)

  const runDelete = async () => {
    const r = await del.mutateAsync(selectedDns)
    setConfirmDelete(false)
    setSelection({})
    if (r.failed) toast.error(t('listing.bulkPartial', { ok: r.ok, failed: r.failed }))
    else toast.success(t('listing.deleted', { count: r.ok }))
  }
  const runLock = async (doLock: boolean) => {
    const r = await lock.mutateAsync({ dns: selectedDns, lock: doLock })
    setSelection({})
    if (r.failed) toast.error(t('listing.bulkPartial', { ok: r.ok, failed: r.failed }))
    else toast.success(t(doLock ? 'listing.lockedCount' : 'listing.unlockedCount', { count: r.ok }))
  }

  if (desc.isError) return <ErrorState error={desc.error} onRetry={() => void desc.refetch()} />

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{label}</h1>
          <p className="text-muted-foreground text-sm" aria-live="polite">
            {list.isSuccess ? t('listing.count', { count: total ?? rows.length }) : ' '}
          </p>
        </div>
        {summary?.can_create && (
          <Button asChild>
            <Link to="/types/$type/new" params={{ type }}>
              <Plus className="size-4" />
              {t('listing.create', { type: desc.data?.label ?? type })}
            </Link>
          </Button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative max-w-sm min-w-56 flex-1">
          <Search className="text-muted-foreground absolute top-2.5 left-2.5 size-4" aria-hidden />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('listing.searchPlaceholder', { type: label.toLowerCase() })}
            aria-label={t('listing.search')}
            className="pl-8"
            type="search"
          />
        </div>
        <div role="group" aria-label={t('listing.scope')} className="bg-muted inline-flex rounded-lg p-0.5">
          {(['one', 'sub'] as const).map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={scope === s}
              onClick={() => setScope(s)}
              className={cn(
                'rounded-md px-3 py-1.5 text-sm font-medium',
                scope === s ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {t(`listing.scope_${s}`)}
            </button>
          ))}
        </div>
      </div>

      {selectedDns.length > 0 && (
        <div
          role="region"
          aria-label={t('listing.bulkActions')}
          className="bg-primary-soft flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2"
        >
          <span className="text-sm font-medium">{t('listing.selected', { count: selectedDns.length })}</span>
          <div className="ml-auto flex gap-2">
            {type === 'user' && (
              <>
                <Button size="sm" variant="outline" onClick={() => void runLock(true)}>
                  <Lock className="size-4" />
                  {t('listing.lock')}
                </Button>
                <Button size="sm" variant="outline" onClick={() => void runLock(false)}>
                  <LockOpen className="size-4" />
                  {t('listing.unlock')}
                </Button>
              </>
            )}
            <Button size="sm" variant="outline" className="text-destructive" onClick={() => setConfirmDelete(true)}>
              <Trash2 className="size-4" />
              {t('common.delete')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelection({})} aria-label={t('listing.clearSelection')}>
              <X className="size-4" />
            </Button>
          </div>
        </div>
      )}

      {list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.isPending ? (
        <div className="space-y-2" aria-busy="true" aria-label={t('common.loading')}>
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-11 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Inbox className="size-8" />}
          title={dq ? t('listing.noMatches') : t('listing.empty')}
          description={dq ? t('listing.noMatchesHelp') : undefined}
        />
      ) : (
        <div className="bg-card overflow-hidden rounded-xl border shadow-xs">
          <div ref={scroller} className="max-h-[calc(100vh-18rem)] min-h-40 overflow-auto">
            <table className="w-full caption-bottom text-sm">
              <thead className="bg-card sticky top-0 z-10 shadow-[0_1px_0_var(--border)]">
                {table.getHeaderGroups().map((hg) => (
                  <tr key={hg.id}>
                    {hg.headers.map((h) => {
                      const sorted = h.column.getIsSorted()
                      const canSort = h.column.getCanSort()
                      return (
                        <th
                          key={h.id}
                          scope="col"
                          aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : undefined}
                          className={cn('text-muted-foreground h-10 px-3 text-left text-xs font-medium', h.id === 'select' && 'w-10')}
                        >
                          {canSort ? (
                            <button
                              type="button"
                              className="hover:text-foreground inline-flex items-center gap-1"
                              onClick={h.column.getToggleSortingHandler()}
                            >
                              {String(h.column.columnDef.header)}
                              {sorted === 'asc' ? (
                                <ArrowUp className="size-3" aria-hidden />
                              ) : sorted === 'desc' ? (
                                <ArrowDown className="size-3" aria-hidden />
                              ) : (
                                <ArrowUpDown className="size-3 opacity-40" aria-hidden />
                              )}
                            </button>
                          ) : h.isPlaceholder ? null : (
                            flexRender(h.column.columnDef.header, h.getContext())
                          )}
                        </th>
                      )
                    })}
                  </tr>
                ))}
              </thead>
              <tbody>
                {padTop > 0 && (
                  <tr aria-hidden style={{ height: padTop }}>
                    <td colSpan={columns.length} />
                  </tr>
                )}
                {items.map((vi) => {
                  const row = tableRows[vi.index]
                  if (!row) return null
                  return (
                    <tr
                      key={row.id}
                      data-state={row.getIsSelected() ? 'selected' : undefined}
                      style={{ height: ROW_HEIGHT }}
                      className="hover:bg-accent/60 data-[state=selected]:bg-primary-soft cursor-pointer border-b last:border-0"
                      onClick={() =>
                        void navigate({ to: '/types/$type/$dn', params: { type, dn: row.original.dn } })
                      }
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="truncate px-3">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  )
                })}
                {padBottom > 0 && (
                  <tr aria-hidden style={{ height: padBottom }}>
                    <td colSpan={columns.length} />
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="text-muted-foreground flex items-center justify-between border-t px-3 py-2 text-xs">
            <span>{t('listing.showing', { shown: rows.length, total: total ?? rows.length })}</span>
            {hasNextPage && (
              <Button
                size="sm"
                variant="ghost"
                disabled={isFetchingNextPage}
                onClick={() => void fetchNextPage()}
              >
                {isFetchingNextPage ? t('common.loading') : t('listing.loadMore')}
              </Button>
            )}
          </div>
        </div>
      )}

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('listing.deleteTitle', { count: selectedDns.length })}</AlertDialogTitle>
            <AlertDialogDescription>{t('editor.deleteBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => void runDelete()}
            >
              {t('common.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

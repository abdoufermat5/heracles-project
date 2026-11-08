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
  Copy,
  ExternalLink,
  Lock,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { ObjectListItem, TypeDescriptor } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { formatCellValue, isMonospaceKey, type Density } from './types'

interface ListingTableProps {
  type: string
  descriptor: TypeDescriptor
  rows: ObjectListItem[]
  total: number | null
  sorting: SortingState
  onSortingChange: (sorting: SortingState) => void
  selection: RowSelectionState
  onSelectionChange: (selection: RowSelectionState) => void
  columnVisibility: Record<string, boolean>
  density: Density
  hasNextPage?: boolean
  isFetchingNextPage?: boolean
  onFetchNextPage: () => void
  onRowClick?: (item: ObjectListItem) => void
  onDeleteSingle?: (item: ObjectListItem) => void
  selectedRowDn?: string | null
}

export function ListingTable({
  type,
  descriptor,
  rows,
  total,
  sorting,
  onSortingChange,
  selection,
  onSelectionChange,
  columnVisibility,
  density,
  hasNextPage,
  isFetchingNextPage,
  onFetchNextPage,
  onRowClick,
  onDeleteSingle,
  selectedRowDn,
}: ListingTableProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const lastClickedIndexRef = useRef<number | null>(null)
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null)
  const scrollerRef = useRef<HTMLDivElement>(null)

  const linkKey = descriptor.main_attr ?? descriptor.columns[0]?.key
  const rowHeight = density === 'compact' ? 30 : 36

  const handleCopyDn = useCallback(
    (e: React.MouseEvent, dn: string) => {
      e.stopPropagation()
      void navigator.clipboard.writeText(dn)
      toast.success(t('listing.dnCopied'))
    },
    [t],
  )

  const columns = useMemo<ColumnDef<ObjectListItem>[]>(() => {
    const cols: ColumnDef<ObjectListItem>[] = [
      {
        id: 'select',
        enableSorting: false,
        header: ({ table }) => (
          <div className="flex items-center justify-center">
            <Checkbox
              checked={
                table.getIsAllRowsSelected()
                  ? true
                  : table.getIsSomeRowsSelected()
                    ? 'indeterminate'
                    : false
              }
              onCheckedChange={(v) => table.toggleAllRowsSelected(v === true)}
              aria-label={t('listing.selectAll')}
            />
          </div>
        ),
        cell: ({ row }) => (
          <div
            className="flex items-center justify-center"
            onClick={(e) => e.stopPropagation()}
          >
            <Checkbox
              checked={row.getIsSelected()}
              onCheckedChange={(checked) => {
                const currentIndex = row.index
                if (
                  lastClickedIndexRef.current !== null &&
                  (window.event as MouseEvent)?.shiftKey
                ) {
                  const start = Math.min(lastClickedIndexRef.current, currentIndex)
                  const end = Math.max(lastClickedIndexRef.current, currentIndex)
                  const newSelection = { ...selection }
                  const targetState = checked === true
                  for (let i = start; i <= end; i++) {
                    const r = rows[i]
                    if (r) {
                      if (targetState) newSelection[r.dn] = true
                      else delete newSelection[r.dn]
                    }
                  }
                  onSelectionChange(newSelection)
                } else {
                  row.toggleSelected(checked === true)
                }
                lastClickedIndexRef.current = currentIndex
              }}
              aria-label={t('listing.selectRow', {
                name: String(row.original.values[descriptor.name_attr] ?? row.original.dn),
              })}
            />
          </div>
        ),
      },
      ...descriptor.columns.map<ColumnDef<ObjectListItem>>((c) => ({
        id: c.key,
        header: c.label,
        accessorFn: (r) => r.values[c.key],
        cell: ({ row, getValue }) => {
          const rawVal = getValue()
          const text = formatCellValue(rawVal, t('common.yes'), t('common.no'))
          const mono = isMonospaceKey(c.key)

          if (c.key !== linkKey) {
            return (
              <span
                className={cn(
                  'block truncate text-muted-foreground',
                  mono && 'font-mono text-[13px] text-foreground/80',
                )}
                title={text}
              >
                {text}
              </span>
            )
          }

          return (
            <div className="flex min-w-0 items-center gap-2">
              <Link
                to="/types/$type/$dn"
                params={{ type, dn: row.original.dn }}
                className={cn(
                  'truncate text-[13px] font-medium text-foreground hover:text-signal focus-visible:underline focus-visible:outline-none',
                  mono && 'font-mono',
                )}
                onClick={(e) => e.stopPropagation()}
                title={text}
              >
                {text}
              </Link>
              {row.original.locked && (
                <Badge
                  variant="warning"
                  className="h-5 shrink-0 gap-1 rounded-sm px-1.5 text-[11px]"
                >
                  <Lock className="size-3" aria-hidden />
                  {t('listing.locked')}
                </Badge>
              )}
            </div>
          )
        },
      })),
      {
        id: 'actions',
        enableSorting: false,
        header: () => <span className="sr-only">{t('listing.actions')}</span>,
        cell: ({ row }) => (
          <div
            className="flex items-center justify-end gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
            onClick={(e) => e.stopPropagation()}
          >
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="text-muted-foreground hover:text-foreground"
                  onClick={(e) => handleCopyDn(e, row.original.dn)}
                  aria-label={t('listing.copyDn')}
                >
                  <Copy aria-hidden />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t('listing.copyDn')}</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  asChild
                  variant="ghost"
                  size="icon-xs"
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={t('listing.open')}
                >
                  <Link to="/types/$type/$dn" params={{ type, dn: row.original.dn }}>
                    <ExternalLink aria-hidden />
                  </Link>
                </Button>
              </TooltipTrigger>
              <TooltipContent>{t('listing.open')}</TooltipContent>
            </Tooltip>

            {onDeleteSingle && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    className="text-muted-foreground hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDeleteSingle(row.original)
                    }}
                    aria-label={t('common.delete')}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('common.delete')}</TooltipContent>
              </Tooltip>
            )}
          </div>
        ),
      },
    ]
    return cols
  }, [
    descriptor,
    handleCopyDn,
    linkKey,
    onDeleteSingle,
    onSelectionChange,
    rows,
    selection,
    t,
    type,
  ])

  const table = useReactTable({
    data: rows,
    columns,
    getRowId: (r) => r.dn,
    getCoreRowModel: getCoreRowModel(),
    state: {
      sorting,
      rowSelection: selection,
      columnVisibility,
    },
    onSortingChange: (updater) => {
      const next = typeof updater === 'function' ? updater(sorting) : updater
      onSortingChange(next)
    },
    onRowSelectionChange: (updater) => {
      const next = typeof updater === 'function' ? updater(selection) : updater
      onSelectionChange(next)
    },
    manualSorting: true,
    enableSortingRemoval: true,
    enableMultiSort: false,
  })

  const tableRows = table.getRowModel().rows

  const virtual = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => scrollerRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
    initialRect: { width: 800, height: 600 },
    observeElementRect: (instance, cb) =>
      observeElementRect(instance, (rect) =>
        cb(rect.height === 0 ? { width: rect.width, height: 600 } : rect),
      ),
  })

  const virtualItems = virtual.getVirtualItems()
  const lastIndex = virtualItems.length
    ? (virtualItems[virtualItems.length - 1]?.index ?? 0)
    : 0

  useEffect(() => {
    if (
      hasNextPage &&
      !isFetchingNextPage &&
      tableRows.length > 0 &&
      lastIndex >= tableRows.length - 8
    ) {
      onFetchNextPage()
    }
  }, [lastIndex, tableRows.length, hasNextPage, isFetchingNextPage, onFetchNextPage])

  const padTop = virtualItems.length ? (virtualItems[0]?.start ?? 0) : 0
  const padBottom = virtualItems.length
    ? virtual.getTotalSize() - (virtualItems[virtualItems.length - 1]?.end ?? 0)
    : 0

  // Keyboard navigation across rows
  const handleTableKeyDown = (e: React.KeyboardEvent) => {
    if (tableRows.length === 0) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setFocusedIndex((prev) => {
        const next = prev === null ? 0 : Math.min(prev + 1, tableRows.length - 1)
        virtual.scrollToIndex(next, { align: 'auto' })
        return next
      })
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setFocusedIndex((prev) => {
        const next = prev === null ? 0 : Math.max(prev - 1, 0)
        virtual.scrollToIndex(next, { align: 'auto' })
        return next
      })
    } else if (e.key === 'Enter') {
      if (focusedIndex !== null && tableRows[focusedIndex]) {
        e.preventDefault()
        const target = tableRows[focusedIndex]
        void navigate({
          to: '/types/$type/$dn',
          params: { type, dn: target.original.dn },
        })
      }
    } else if (e.key === ' ') {
      if (focusedIndex !== null && tableRows[focusedIndex]) {
        e.preventDefault()
        tableRows[focusedIndex].toggleSelected()
      }
    }
  }

  return (
    <div
      className="overflow-hidden rounded-b-md border bg-card outline-none"
      tabIndex={0}
      onKeyDown={handleTableKeyDown}
      role="region"
      aria-label={descriptor.label}
    >
      <div
        ref={scrollerRef}
        className="min-h-56 max-h-[calc(100vh-18rem)] overflow-auto"
      >
        <table className="w-full border-collapse text-[13px]">
          <thead className="sticky top-0 z-10 bg-muted/50">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b">
                {hg.headers.map((h) => {
                  const sorted = h.column.getIsSorted()
                  const canSort = h.column.getCanSort()
                  return (
                    <th
                      key={h.id}
                      scope="col"
                      aria-sort={
                        sorted === 'asc'
                          ? 'ascending'
                          : sorted === 'desc'
                            ? 'descending'
                            : undefined
                      }
                      className={cn(
                        'h-8 px-3 text-left select-none',
                        h.id === 'select' && 'w-10 text-center',
                        h.id === 'actions' && 'w-20 text-right',
                      )}
                    >
                      {canSort ? (
                        <button
                          type="button"
                          className={cn(
                            'label-caps inline-flex items-center gap-1 rounded-sm py-0.5 transition-colors hover:text-foreground focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none',
                            sorted ? 'text-foreground' : 'text-muted-foreground',
                          )}
                          onClick={h.column.getToggleSortingHandler()}
                        >
                          <span>{String(h.column.columnDef.header)}</span>
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
            {virtualItems.map((vi) => {
              const row = tableRows[vi.index]
              if (!row) return null
              const isSelected = row.getIsSelected()
              const isFocused = focusedIndex === vi.index
              const isPreviewSelected = selectedRowDn === row.original.dn

              return (
                <tr
                  key={row.id}
                  data-state={isSelected ? 'selected' : undefined}
                  style={{ height: rowHeight }}
                  className={cn(
                    'group cursor-pointer border-b transition-colors last:border-b-0 hover:bg-accent/50',
                    isSelected && 'bg-primary-soft hover:bg-primary-soft',
                    isPreviewSelected && 'bg-accent/70',
                    isFocused && 'ring-1 ring-inset ring-signal/50',
                  )}
                  onClick={() => {
                    setFocusedIndex(vi.index)
                    if (onRowClick) onRowClick(row.original)
                    else {
                      void navigate({
                        to: '/types/$type/$dn',
                        params: { type, dn: row.original.dn },
                      })
                    }
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className={cn(
                        'truncate px-3',
                        cell.column.id === 'select' && 'w-10 text-center',
                        cell.column.id === 'actions' && 'w-20 text-right',
                      )}
                    >
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

      {/* Table Footer */}
      <div className="flex h-10 items-center justify-between border-t px-3 text-xs text-muted-foreground">
        <div className="flex items-center gap-2 tabular-nums">
          <span>
            {t('listing.showing', {
              shown: rows.length,
              total: total ?? rows.length,
            })}
          </span>
          {Object.keys(selection).length > 0 && (
            <span className="font-medium text-foreground">
              ({t('listing.selected', { count: Object.keys(selection).length })})
            </span>
          )}
        </div>
        {hasNextPage && (
          <Button
            size="sm"
            variant="outline"
            disabled={isFetchingNextPage}
            onClick={onFetchNextPage}
          >
            {isFetchingNextPage ? t('common.loading') : t('listing.loadMore')}
          </Button>
        )}
      </div>
    </div>
  )
}

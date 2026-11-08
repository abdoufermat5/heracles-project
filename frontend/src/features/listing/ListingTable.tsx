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
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import {
  formatCellValue,
  getInitials,
  isMonospaceKey,
  type Density,
} from './types'

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

  const isPerson = type === 'user'
  const linkKey = descriptor.main_attr ?? descriptor.columns[0]?.key
  const rowHeight = density === 'compact' ? 34 : 42

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
                  'text-muted-foreground block truncate',
                  mono && 'font-mono text-xs text-foreground/80',
                )}
                title={text}
              >
                {text}
              </span>
            )
          }

          // Main primary attribute column
          const displayName = String(
            row.original.values[descriptor.name_attr] ??
              row.original.values[descriptor.main_attr] ??
              text,
          )

          return (
            <div className="flex items-center gap-2.5 min-w-0">
              {isPerson && (
                <Avatar className="size-6 shrink-0 ring-1 ring-border">
                  <AvatarFallback className="text-[10px] font-semibold bg-muted text-muted-foreground">
                    {getInitials(displayName)}
                  </AvatarFallback>
                </Avatar>
              )}
              <Link
                to="/types/$type/$dn"
                params={{ type, dn: row.original.dn }}
                className={cn(
                  'hover:text-primary truncate font-medium text-foreground focus-visible:underline focus-visible:outline-none',
                  mono && 'font-mono text-xs',
                )}
                onClick={(e) => e.stopPropagation()}
                title={text}
              >
                {text}
              </Link>
              {row.original.locked && (
                <Badge
                  variant="outline"
                  className="text-warning border-warning/40 h-4.5 gap-1 px-1.5 text-[10px] shrink-0"
                >
                  <Lock className="size-2.5" aria-hidden />
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
            className="flex items-center justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
            onClick={(e) => e.stopPropagation()}
          >
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="size-7 text-muted-foreground hover:text-foreground"
                  onClick={(e) => handleCopyDn(e, row.original.dn)}
                  aria-label={t('listing.copyDn')}
                >
                  <Copy className="size-3.5" aria-hidden />
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
                  className="size-7 text-muted-foreground hover:text-foreground"
                  aria-label={t('listing.open')}
                >
                  <Link to="/types/$type/$dn" params={{ type, dn: row.original.dn }}>
                    <ExternalLink className="size-3.5" aria-hidden />
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
                    className="size-7 text-muted-foreground hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDeleteSingle(row.original)
                    }}
                    aria-label={t('common.delete')}
                  >
                    <Trash2 className="size-3.5" aria-hidden />
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
    isPerson,
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
      className="bg-card overflow-hidden rounded-xl border border-border shadow-xs outline-none"
      tabIndex={0}
      onKeyDown={handleTableKeyDown}
      role="region"
      aria-label={descriptor.label}
    >
      <div
        ref={scrollerRef}
        className="max-h-[calc(100vh-18rem)] min-h-56 overflow-auto"
      >
        <table className="w-full caption-bottom text-sm border-collapse">
          <thead className="bg-muted/40 sticky top-0 z-10 border-b border-border shadow-xs backdrop-blur-xs">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
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
                        'text-muted-foreground h-9 px-3 text-left text-xs font-semibold select-none',
                        h.id === 'select' && 'w-10 text-center',
                        h.id === 'actions' && 'w-24 text-right',
                      )}
                    >
                      {canSort ? (
                        <button
                          type="button"
                          className="hover:text-foreground inline-flex items-center gap-1.5 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-sm py-0.5"
                          onClick={h.column.getToggleSortingHandler()}
                        >
                          <span>{String(h.column.columnDef.header)}</span>
                          {sorted === 'asc' ? (
                            <ArrowUp className="size-3 text-primary" aria-hidden />
                          ) : sorted === 'desc' ? (
                            <ArrowDown className="size-3 text-primary" aria-hidden />
                          ) : (
                            <ArrowUpDown className="size-3 opacity-30" aria-hidden />
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
          <tbody className="divide-y divide-border/60">
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
                    'group hover:bg-accent/50 cursor-pointer transition-colors',
                    isSelected && 'bg-primary-soft/60 hover:bg-primary-soft',
                    isPreviewSelected && 'bg-accent/80 ring-1 ring-inset ring-primary/40',
                    isFocused && 'ring-2 ring-inset ring-primary/60',
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
                        'truncate px-3 text-xs',
                        cell.column.id === 'select' && 'w-10 text-center',
                        cell.column.id === 'actions' && 'w-24 text-right',
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
      <div className="bg-card text-muted-foreground flex items-center justify-between border-t border-border px-3.5 py-2 text-xs">
        <div className="flex items-center gap-2">
          <span>
            {t('listing.showing', {
              shown: rows.length,
              total: total ?? rows.length,
            })}
          </span>
          {Object.keys(selection).length > 0 && (
            <span className="text-primary font-medium">
              ({t('listing.selected', { count: Object.keys(selection).length })})
            </span>
          )}
        </div>
        {hasNextPage && (
          <Button
            size="sm"
            variant="ghost"
            disabled={isFetchingNextPage}
            onClick={onFetchNextPage}
            className="h-7 text-xs"
          >
            {isFetchingNextPage ? t('common.loading') : t('listing.loadMore')}
          </Button>
        )}
      </div>
    </div>
  )
}

import { Link, useNavigate } from '@tanstack/react-router'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type ColumnSizingState,
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
  FolderInput,
  Lock,
  MoreHorizontal,
  Trash2,
} from 'lucide-react'
import { useCallback, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { ObjectListItem, TypeDescriptor } from '@/api/types'
import { OrgPath, StatusBadge } from '@/components/patterns'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { getUserStatus } from '@/features/people/utils'
import { attributeLabel } from '@/lib/labels'
import { cn, initials } from '@/lib/utils'
import { formatCellValue, isMonospaceKey, type Density } from './types'

/** Member count the listing reports on a group row (the field is absent on other rows). */
function memberCount(item: ObjectListItem): number | undefined {
  const n = item.members_count
  return typeof n === 'number' ? n : undefined
}

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
  /** Preferred order of the data columns (ids); unlisted ones keep their default place. */
  columnOrder?: string[]
  columnSizing?: ColumnSizingState
  onColumnSizingChange?: (sizing: ColumnSizingState) => void
  density: Density
  onRowClick?: (item: ObjectListItem) => void
  onDeleteSingle?: (item: ObjectListItem) => void
  onCopyTo?: (item: ObjectListItem) => void
  onMoveTo?: (item: ObjectListItem) => void
  selectedRowDn?: string | null
}

export function ListingTable({
  type,
  descriptor,
  rows,
  sorting,
  onSortingChange,
  selection,
  onSelectionChange,
  columnVisibility,
  columnOrder = [],
  columnSizing = {},
  onColumnSizingChange,
  density,
  onRowClick,
  onDeleteSingle,
  onCopyTo,
  onMoveTo,
  selectedRowDn,
}: ListingTableProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const lastClickedIndexRef = useRef<number | null>(null)
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null)
  const scrollerRef = useRef<HTMLDivElement>(null)

  const isUser = type === 'user'
  const rowHeight = isUser ? (density === 'compact' ? 44 : 52) : density === 'compact' ? 30 : 36

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
    ]

    if (isUser) {
      // 1. Person column (avatar, display name, login underneath)
      cols.push({
        id: 'person',
        header: t('peopleUI.columns.person'),
        accessorFn: (r) => String(r.values[descriptor.name_attr] ?? r.values[descriptor.main_attr] ?? r.dn),
        cell: ({ row }) => {
          const name = String(row.original.values[descriptor.name_attr] ?? row.original.values.cn ?? 'User')
          const login = String(row.original.values[descriptor.main_attr] ?? row.original.values.uid ?? '')
          return (
            <div className="flex items-center gap-3 min-w-0">
              <Avatar className="size-8 shrink-0">
                <AvatarFallback className="bg-primary-soft text-caption font-semibold text-primary">
                  {initials(name)}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0">
                <Link
                  to="/types/$type/$dn"
                  params={{ type, dn: row.original.dn }}
                  className="truncate font-medium text-foreground hover:text-signal focus-visible:underline focus-visible:outline-none block"
                  onClick={(e) => e.stopPropagation()}
                  title={name}
                >
                  {name}
                </Link>
                {login && (
                  <span className="truncate text-caption text-muted-foreground block font-mono">
                    {login}
                  </span>
                )}
              </div>
            </div>
          )
        },
      })

      // 2. Status column
      cols.push({
        id: 'status',
        header: t('peopleUI.columns.status'),
        accessorFn: (r) => (r.locked ? 'locked' : 'active'),
        cell: ({ row }) => {
          const status = getUserStatus(row.original)
          return <StatusBadge status={status} />
        },
      })

      // 3. Department column (OrgPath)
      cols.push({
        id: 'department',
        header: t('peopleUI.columns.department'),
        cell: ({ row }) => (
          typeof row.original.values.base === 'string' ? (
            <OrgPath dn={row.original.values.base} includeSelf />
          ) : (
            <OrgPath dn={row.original.dn} />
          )
        ),
      })

      // 4. Email column
      cols.push({
        id: 'mail',
        header: t('peopleUI.columns.email'),
        accessorFn: (r) => r.values.mail,
        cell: ({ row }) => {
          const mail = row.original.values.mail
          return (
            <span className="block truncate text-muted-foreground" title={String(mail ?? '')}>
              {mail ? String(mail) : '—'}
            </span>
          )
        },
      })

      // 5. Groups count column
      cols.push({
        id: 'groups',
        header: t('peopleUI.columns.groups'),
        accessorFn: (r) => r.groups_count ?? (r.values.groups_count as number) ?? 0,
        cell: ({ row }) => {
          const count = row.original.groups_count ?? (row.original.values.groups_count as number) ?? 0
          return <span className="tabular-nums font-medium text-foreground">{count}</span>
        },
      })

      // 6. Any other columns from descriptor not in the standard set
      const coreKeys: Record<string, true> = {
        uid: true,
        cn: true,
        mail: true,
        person: true,
        status: true,
        department: true,
        groups: true,
      }
      descriptor.columns.forEach((c) => {
        if (coreKeys[c.key]) return
        cols.push({
          id: c.key,
          header: attributeLabel(t, c.key, c.label),
          accessorFn: (r) => r.values[c.key],
          cell: ({ getValue }) => {
            const rawVal = getValue()
            const text = formatCellValue(rawVal, t('common.yes'), t('common.no'))
            const mono = isMonospaceKey(c.key)
            return (
              <span
                className={cn('block truncate text-muted-foreground', mono && 'font-mono text-body text-foreground/80')}
                title={text}
              >
                {text}
              </span>
            )
          },
        })
      })
    } else {
      // Non-user generic columns
      const linkKey = descriptor.main_attr ?? descriptor.columns[0]?.key
      descriptor.columns.forEach((c) => {
        cols.push({
          id: c.key,
          header: attributeLabel(t, c.key, c.label),
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
                    mono && 'font-mono text-body text-foreground/80',
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
                    'truncate text-body font-medium text-foreground hover:text-signal focus-visible:underline focus-visible:outline-none',
                    mono && 'font-mono',
                  )}
                  onClick={(e) => e.stopPropagation()}
                  title={text}
                >
                  {text}
                </Link>
                {row.original.locked && (
                  <Badge variant="warning" className="h-5 shrink-0 gap-1 rounded-sm px-1.5 text-caption">
                    <Lock className="size-3" aria-hidden />
                    {t('listing.locked')}
                  </Badge>
                )}
              </div>
            )
          },
        })
      })

      // Groups: the member count, as soon as the listing reports it
      if (type === 'group' && rows.some((r) => memberCount(r) !== undefined)) {
        cols.push({
          id: 'members',
          header: t('listingUI.members'),
          enableSorting: false,
          accessorFn: (r) => memberCount(r),
          cell: ({ getValue }) => (
            <span className="font-medium tabular-nums text-foreground">
              {String(getValue() ?? '—')}
            </span>
          ),
        })
      }
    }

    // Actions column
    cols.push({
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

          {(onCopyTo || onMoveTo || onDeleteSingle) && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={t('copy.rowMenu')}
                >
                  <MoreHorizontal aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                {onCopyTo && (
                  <DropdownMenuItem onClick={() => onCopyTo(row.original)}>
                    <Copy className="size-4" />
                    {t('copy.copyTo')}
                  </DropdownMenuItem>
                )}
                {onMoveTo && (
                  <DropdownMenuItem onClick={() => onMoveTo(row.original)}>
                    <FolderInput className="size-4" />
                    {t('copy.moveTo')}
                  </DropdownMenuItem>
                )}
                {onDeleteSingle && (
                  <DropdownMenuItem
                    onClick={() => onDeleteSingle(row.original)}
                    className="text-destructive focus:text-destructive"
                  >
                    <Trash2 className="size-4" />
                    {t('listing.delete')}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      ),
    })

    return cols
  }, [
    descriptor,
    handleCopyDn,
    isUser,
    onCopyTo,
    onDeleteSingle,
    onMoveTo,
    onSelectionChange,
    rows,
    selection,
    t,
    type,
  ])

  const orderedIds = useMemo(() => {
    const ids = columns.map((c) => c.id ?? '')
    const middle = ids.filter((id) => id !== 'select' && id !== 'actions')
    const preferred = columnOrder.filter((id) => middle.includes(id))
    const rest = middle.filter((id) => !preferred.includes(id))
    return ['select', ...preferred, ...rest, 'actions']
  }, [columns, columnOrder])

  const table = useReactTable({
    data: rows,
    columns,
    getRowId: (r) => r.dn,
    getCoreRowModel: getCoreRowModel(),
    state: {
      sorting,
      rowSelection: selection,
      columnVisibility,
      columnSizing,
      columnOrder: orderedIds,
    },
    enableColumnResizing: true,
    columnResizeMode: 'onChange',
    onColumnSizingChange: (updater) => {
      const next = typeof updater === 'function' ? updater(columnSizing) : updater
      onColumnSizingChange?.(next)
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
    overscan: 10,
    initialRect: { width: 800, height: 600 },
    observeElementRect: (instance, cb) =>
      observeElementRect(instance, (rect) =>
        cb(rect.height === 0 ? { width: rect.width, height: 600 } : rect),
      ),
  })

  const virtualItems = virtual.getVirtualItems()

  const padTop = virtualItems.length ? (virtualItems[0]?.start ?? 0) : 0
  const padBottom = virtualItems.length
    ? virtual.getTotalSize() - (virtualItems[virtualItems.length - 1]?.end ?? 0)
    : 0

  const moveCursor = (delta: number) => {
    setFocusedIndex((prev) => {
      const next =
        prev === null ? 0 : Math.max(0, Math.min(prev + delta, tableRows.length - 1))
      virtual.scrollToIndex(next, { align: 'auto' })
      return next
    })
  }

  // Focus-scoped: only active while the table has the keyboard focus.
  const handleTableKeyDown = (e: React.KeyboardEvent) => {
    if (tableRows.length === 0 || e.ctrlKey || e.metaKey || e.altKey) return
    const target = e.target as HTMLElement
    if (target.closest('input, textarea, select, [contenteditable="true"]')) return
    const current = focusedIndex !== null ? tableRows[focusedIndex] : undefined

    if (e.key === 'ArrowDown' || e.key === 'j') {
      e.preventDefault()
      moveCursor(1)
    } else if (e.key === 'ArrowUp' || e.key === 'k') {
      e.preventDefault()
      moveCursor(-1)
    } else if (current && (e.key === 'Enter' || e.key === 'o')) {
      e.preventDefault()
      const item = current.original
      if (onRowClick) onRowClick(item)
      else void navigate({ to: '/types/$type/$dn', params: { type, dn: item.dn } })
    } else if (current && e.key === 'x') {
      e.preventDefault()
      current.toggleSelected()
    } else if (current && e.key === 'e') {
      e.preventDefault()
      void navigate({
        to: '/types/$type/$dn',
        params: { type, dn: current.original.dn },
        search: { view: 'generic', edit: true },
      })
    }
  }

  return (
    <div>
      {/* Mobile Card List (under md) */}
      <div className="grid gap-2 md:hidden">
        {rows.map((item) => {
          const name = String(item.values[descriptor.name_attr] ?? item.values.cn ?? item.dn)
          const login = String(item.values[descriptor.main_attr] ?? item.values.uid ?? '')
          const isSelected = Boolean(selection[item.dn])

          return (
            <div
              key={item.dn}
              className={cn(
                'flex flex-col gap-2 rounded-lg border bg-card p-3 shadow-xs transition-colors hover:bg-muted/30 cursor-pointer',
                isSelected && 'border-primary/50 bg-primary-soft/30',
              )}
              onClick={() => onRowClick?.(item)}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-3 min-w-0">
                  <div onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={isSelected}
                      onCheckedChange={(checked) => {
                        onSelectionChange({
                          ...selection,
                          [item.dn]: checked === true,
                        })
                      }}
                      aria-label={t('listing.selectRow', { name })}
                    />
                  </div>
                  {isUser && (
                    <Avatar className="size-9 shrink-0">
                      <AvatarFallback className="bg-primary-soft text-caption font-semibold text-primary">
                        {initials(name)}
                      </AvatarFallback>
                    </Avatar>
                  )}
                  <div className="min-w-0">
                    <Link
                      to="/types/$type/$dn"
                      params={{ type, dn: item.dn }}
                      className="truncate font-medium text-foreground hover:text-signal block"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {name}
                    </Link>
                    {isUser && login && (
                      <span className="truncate text-caption text-muted-foreground block font-mono">
                        {login}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  {isUser && <StatusBadge status={getUserStatus(item)} />}
                  {(onCopyTo || onMoveTo || onDeleteSingle) && (
                    <div onClick={(e) => e.stopPropagation()}>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-xs">
                            <MoreHorizontal className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => handleCopyDn({ stopPropagation: () => {} } as React.MouseEvent, item.dn)}>
                            <Copy className="size-4" />
                            {t('listing.copyDn')}
                          </DropdownMenuItem>
                          {onMoveTo && (
                            <DropdownMenuItem onClick={() => onMoveTo(item)}>
                              <FolderInput className="size-4" />
                              {t('listing.moveTo')}
                            </DropdownMenuItem>
                          )}
                          {onDeleteSingle && (
                            <DropdownMenuItem
                              onClick={() => onDeleteSingle(item)}
                              className="text-destructive focus:text-destructive"
                            >
                              <Trash2 className="size-4" />
                              {t('listing.delete')}
                            </DropdownMenuItem>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-2 text-caption text-muted-foreground">
                {typeof item.values.base === 'string' ? (
                  <OrgPath dn={item.values.base} includeSelf className="min-w-0" />
                ) : (
                  <OrgPath dn={item.dn} className="min-w-0" />
                )}
                {isUser && (
                  <span className="tabular-nums">
                    {t('peopleUI.mobile.groupsCount', {
                      count: item.groups_count ?? (item.values.groups_count as number) ?? 0,
                    })}
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Desktop Table (md and up) */}
      <div
        ref={scrollerRef}
        tabIndex={0}
        onKeyDown={handleTableKeyDown}
        aria-label={t('safety.shortcuts')}
        className="hidden md:block relative max-h-[calc(100vh-220px)] overflow-auto rounded-t-md border border-t-0 bg-card outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <table className="w-full border-collapse text-body" style={{ minWidth: 650 }}>
          <thead className="sticky top-0 z-10 border-b bg-card">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const canSort = header.column.getCanSort()
                  const isSorted = header.column.getIsSorted()
                  return (
                    <th
                      key={header.id}
                      style={
                        columnSizing[header.id] !== undefined
                          ? { width: header.getSize(), maxWidth: header.getSize() }
                          : undefined
                      }
                      className={cn(
                        'relative h-10 px-3 text-left text-small font-medium text-muted-foreground select-none',
                        header.id === 'select' && 'w-10 px-0 text-center',
                        header.id === 'actions' && 'w-24 text-right',
                        header.id === 'status' && 'w-32',
                        header.id === 'groups' && 'w-24 text-right',
                      )}
                    >
                      {header.isPlaceholder ? null : canSort ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="flex items-center gap-1.5 transition-colors hover:text-foreground focus-visible:underline focus-visible:outline-none"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {isSorted === 'asc' ? (
                            <ArrowUp className="size-3 text-foreground" aria-hidden />
                          ) : isSorted === 'desc' ? (
                            <ArrowDown className="size-3 text-foreground" aria-hidden />
                          ) : (
                            <ArrowUpDown className="size-3 opacity-40" aria-hidden />
                          )}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                      {header.column.getCanResize() &&
                        header.id !== 'select' &&
                        header.id !== 'actions' && (
                          <div
                            role="separator"
                            aria-orientation="vertical"
                            aria-label={t('safety.resizeColumn', {
                              name: String(header.column.columnDef.header ?? header.id),
                            })}
                            onMouseDown={header.getResizeHandler()}
                            onTouchStart={header.getResizeHandler()}
                            onClick={(e) => e.stopPropagation()}
                            className={cn(
                              'absolute top-0 right-0 h-full w-1.5 cursor-col-resize touch-none select-none hover:bg-ring/50',
                              header.column.getIsResizing() && 'bg-ring',
                            )}
                          />
                        )}
                    </th>
                  )
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {padTop > 0 && (
              <tr>
                <td style={{ height: `${padTop}px` }} />
              </tr>
            )}
            {virtualItems.map((virtualRow) => {
              const row = tableRows[virtualRow.index]
              if (!row) return null
              const isSelected = row.getIsSelected()
              const isFocused = focusedIndex === virtualRow.index
              const isHighlighted = selectedRowDn === row.original.dn

              return (
                <tr
                  key={row.id}
                  data-index={virtualRow.index}
                  data-state={isSelected ? 'selected' : undefined}
                  onClick={() => onRowClick?.(row.original)}
                  className={cn(
                    'group border-b border-border/50 transition-colors cursor-pointer',
                    density === 'compact' ? 'h-[32px]' : isUser ? 'h-[52px]' : 'h-[36px]',
                    isSelected && 'bg-primary-soft/40',
                    isHighlighted && !isSelected && 'bg-muted/60',
                    !isSelected && !isHighlighted && 'hover:bg-muted/30',
                    isFocused && 'ring-1 ring-inset ring-ring',
                  )}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      style={
                        columnSizing[cell.column.id] !== undefined
                          ? { width: cell.column.getSize(), maxWidth: cell.column.getSize() }
                          : undefined
                      }
                      className={cn(
                        'px-3 text-body truncate',
                        cell.column.id === 'select' && 'w-10 px-0 text-center',
                        cell.column.id === 'actions' && 'w-24 text-right overflow-visible',
                        cell.column.id === 'groups' && 'text-right',
                      )}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              )
            })}
            {padBottom > 0 && (
              <tr>
                <td style={{ height: `${padBottom}px` }} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

import { useNavigate } from '@tanstack/react-router'
import type { RowSelectionState, SortingState } from '@tanstack/react-table'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import {
  useAccountLock,
  useDeleteObjects,
  useMe,
  useObjectList,
  useTree,
  useTypeDescriptor,
  useTypes,
} from '@/api/hooks'
import type { ObjectListItem, TreeNode } from '@/api/types'
import { ErrorState } from '@/components/ErrorState'
import { useScope } from '@/lib/scope'
import { exportToCsv } from './csv'
import { ListingBulkBar } from './ListingBulkBar'
import { ListingDeleteDialog } from './ListingDeleteDialog'
import { ListingEmptyState } from './ListingEmptyState'
import { ListingHeader } from './ListingHeader'
import { ListingPermissionDenied } from './ListingPermissionDenied'
import { ListingPreviewPanel } from './ListingPreviewPanel'
import { ListingSkeleton } from './ListingSkeleton'
import { ListingTable } from './ListingTable'
import { ListingToolbar } from './ListingToolbar'
import {
  loadColumnVisibility,
  loadDensity,
  saveColumnVisibility,
  saveDensity,
  type Density,
  type StatusFilter,
} from './types'

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

function findDepartmentLabel(nodes: TreeNode[] | undefined, dn: string | null): string | null {
  if (!nodes || !dn) return null
  for (const n of nodes) {
    if (n.dn.toLowerCase() === dn.toLowerCase()) return n.label
    const child = findDepartmentLabel(n.children, dn)
    if (child) return child
  }
  return null
}

export function ObjectListPage({ type }: { type: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const desc = useTypeDescriptor(type)
  const types = useTypes()
  const me = useMe()
  const tree = useTree()
  const { base, scope, setScope } = useScope()

  // State
  const [searchQuery, setSearchQuery] = useState('')
  const debouncedQuery = useDebounced(searchQuery)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [sorting, setSorting] = useState<SortingState>([])
  const [selection, setSelection] = useState<RowSelectionState>({})
  const [density, setDensity] = useState<Density>(loadDensity)
  const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>(() =>
    loadColumnVisibility(type),
  )
  const [showPreview, setShowPreview] = useState(false)
  const [previewDn, setPreviewDn] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [singleDeleteTarget, setSingleDeleteTarget] = useState<ObjectListItem | null>(null)

  // Handlers for persistence
  const handleDensityChange = (newDensity: Density) => {
    setDensity(newDensity)
    saveDensity(newDensity)
  }

  const handleToggleColumn = (colKey: string) => {
    setColumnVisibility((prev) => {
      const next = { ...prev, [colKey]: prev[colKey] === false }
      saveColumnVisibility(type, next)
      return next
    })
  }

  const handleResetColumns = () => {
    setColumnVisibility({})
    saveColumnVisibility(type, {})
  }

  // Active query parameters
  const currentBase = base ?? me.data?.base
  const sort = sorting[0]
  const list = useObjectList(type, {
    base: currentBase,
    scope,
    q: debouncedQuery || undefined,
    sort: sort?.id,
    order: sort ? (sort.desc ? 'desc' : 'asc') : undefined,
    limit: 50,
  })

  // Rows and summary
  const rawRows: ObjectListItem[] = useMemo(
    () => list.data?.pages.flatMap((p) => p.items) ?? [],
    [list.data],
  )
  const total = list.data?.pages[0]?.total ?? null
  const summary = types.data?.find((x) => x.name === type)
  const label = summary?.label_plural ?? desc.data?.label ?? type

  // Filter rows by status if active
  const rows = useMemo(() => {
    if (statusFilter === 'all') return rawRows
    if (statusFilter === 'locked') return rawRows.filter((r) => r.locked)
    if (statusFilter === 'active') return rawRows.filter((r) => !r.locked)
    return rawRows
  }, [rawRows, statusFilter])

  // Items map for easy lookup
  const itemsMap = useMemo(() => {
    const map = new Map<string, ObjectListItem>()
    for (const r of rawRows) map.set(r.dn, r)
    return map
  }, [rawRows])

  // Reset selection and preview on query/filter changes
  const queryKey = `${type}:${base}:${scope}:${debouncedQuery}:${statusFilter}`
  const [prevQueryKey, setPrevQueryKey] = useState(queryKey)
  if (prevQueryKey !== queryKey) {
    setPrevQueryKey(queryKey)
    setSelection({})
    setPreviewDn(null)
  }

  // Derived preview item
  const previewItem = previewDn ? itemsMap.get(previewDn) ?? null : null

  const selectedDns = useMemo(
    () => Object.keys(selection).filter((k) => selection[k]),
    [selection],
  )

  const del = useDeleteObjects(type)
  const lock = useAccountLock(type)

  const runDelete = async (dns: string[]) => {
    const r = await del.mutateAsync(dns)
    setConfirmDelete(false)
    setSingleDeleteTarget(null)
    setSelection({})
    if (previewDn && dns.includes(previewDn)) {
      setPreviewDn(null)
    }
    if (r.failed) {
      toast.error(t('listing.bulkPartial', { ok: r.ok, failed: r.failed }))
    } else {
      toast.success(t('listing.deleted', { count: r.ok }))
    }
  }

  const runLock = async (dns: string[], doLock: boolean) => {
    const r = await lock.mutateAsync({ dns, lock: doLock })
    setSelection({})
    if (r.failed) {
      toast.error(t('listing.bulkPartial', { ok: r.ok, failed: r.failed }))
    } else {
      toast.success(
        t(doLock ? 'listing.lockedCount' : 'listing.unlockedCount', { count: r.ok }),
      )
    }
  }

  const handleExportCsv = () => {
    if (!desc.data) return
    const exportRows = rows.length > 0 ? rows : rawRows
    exportToCsv(`${type}-export-${new Date().toISOString().slice(0, 10)}`, desc.data.columns, exportRows)
    toast.success(t('listing.exportCsv'))
  }

  const currentDepartmentName = findDepartmentLabel(tree.data, currentBase ?? null)
  const hasFilterActive = Boolean(debouncedQuery || statusFilter !== 'all')

  // Error and permission checks
  const primaryError = desc.error ?? list.error
  if (primaryError) {
    if (isApiError(primaryError) && (primaryError.status === 403 || primaryError.code === 'forbidden')) {
      return (
        <ListingPermissionDenied
          onRetry={() => {
            void desc.refetch()
            void list.refetch()
          }}
        />
      )
    }
    return (
      <ErrorState
        error={primaryError}
        onRetry={() => {
          void desc.refetch()
          void list.refetch()
        }}
      />
    )
  }

  return (
    <div className="space-y-4">
      {/* 1. Page Header */}
      <ListingHeader
        type={type}
        label={label}
        summary={summary}
        descriptor={desc.data}
        total={total}
        isSuccess={list.isSuccess}
        isFetching={list.isFetching && !list.isFetchingNextPage}
        onRefresh={() => void list.refetch()}
        onExportCsv={handleExportCsv}
      />

      {/* 2. Toolbar attached to the table frame, with optional preview panel */}
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <ListingToolbar
            type={type}
            label={label}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            currentDepartmentName={currentDepartmentName}
            scope={scope}
            onScopeChange={setScope}
            statusFilter={statusFilter}
            onStatusFilterChange={setStatusFilter}
            availableColumns={desc.data?.columns ?? []}
            columnVisibility={columnVisibility}
            onToggleColumn={handleToggleColumn}
            onResetColumns={handleResetColumns}
            density={density}
            onDensityChange={handleDensityChange}
            showPreview={showPreview}
            onTogglePreview={() => setShowPreview((p) => !p)}
            supportsStatusFilter={type === 'user'}
          />

          {list.isPending ? (
            <ListingSkeleton
              columns={desc.data?.columns ?? []}
              density={density}
              isPersonType={type === 'user'}
            />
          ) : rows.length === 0 ? (
            <ListingEmptyState
              type={type}
              typeLabel={desc.data?.label}
              isFiltered={hasFilterActive}
              canCreate={summary?.can_create}
              onClearFilter={() => {
                setSearchQuery('')
                setStatusFilter('all')
              }}
            />
          ) : (
            <>
              <ListingBulkBar
                type={type}
                selectedCount={selectedDns.length}
                onLock={
                  type === 'user'
                    ? (doLock) => void runLock(selectedDns, doLock)
                    : undefined
                }
                onDelete={() => setConfirmDelete(true)}
                onClearSelection={() => setSelection({})}
                isLocking={lock.isPending}
                isDeleting={del.isPending}
              />

              {desc.data && (
                <ListingTable
                  type={type}
                  descriptor={desc.data}
                  rows={rows}
                  total={total}
                  sorting={sorting}
                  onSortingChange={setSorting}
                  selection={selection}
                  onSelectionChange={setSelection}
                  columnVisibility={columnVisibility}
                  density={density}
                  hasNextPage={list.hasNextPage}
                  isFetchingNextPage={list.isFetchingNextPage}
                  onFetchNextPage={() => void list.fetchNextPage()}
                  onRowClick={(item) => {
                    if (showPreview) {
                      setPreviewDn(item.dn)
                    } else {
                      void navigate({
                        to: '/types/$type/$dn',
                        params: { type, dn: item.dn },
                      })
                    }
                  }}
                  onDeleteSingle={(item) => setSingleDeleteTarget(item)}
                  selectedRowDn={showPreview ? (previewDn ?? rows[0]?.dn ?? null) : null}
                />
              )}
            </>
          )}
        </div>

        {showPreview && (
          <ListingPreviewPanel
            type={type}
            item={previewItem ?? rows[0] ?? null}
            descriptor={desc.data}
            summary={summary}
            onClose={() => setShowPreview(false)}
            onCopyDn={(dn) => {
              void navigator.clipboard.writeText(dn)
              toast.success(t('listing.dnCopied'))
            }}
            onLockToggle={
              type === 'user' ? (dn, doLock) => void runLock([dn], doLock) : undefined
            }
            onDeleteSingle={(item) => setSingleDeleteTarget(item)}
          />
        )}
      </div>

      {/* 3. Delete Confirmation Dialog (bulk) */}
      <ListingDeleteDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        selectedDns={selectedDns}
        itemsMap={itemsMap}
        nameAttr={desc.data?.name_attr}
        onConfirm={() => void runDelete(selectedDns)}
        isDeleting={del.isPending}
      />

      {/* 4. Single Item Delete Dialog */}
      {singleDeleteTarget && (
        <ListingDeleteDialog
          open={Boolean(singleDeleteTarget)}
          onOpenChange={(open) => !open && setSingleDeleteTarget(null)}
          selectedDns={[singleDeleteTarget.dn]}
          itemsMap={itemsMap}
          nameAttr={desc.data?.name_attr}
          onConfirm={() => void runDelete([singleDeleteTarget.dn])}
          isDeleting={del.isPending}
        />
      )}
    </div>
  )
}

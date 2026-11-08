import { useNavigate } from '@tanstack/react-router'
import type { RowSelectionState, SortingState } from '@tanstack/react-table'
import {
  Copy,
  Download,
  FolderInput,
  Lock,
  LockOpen,
  Pencil,
  Trash2,
  Users,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import {
  useAccountLock,
  useDeleteObjects,
  useMe,
  usePaginatedObjectList,
  useTree,
  useTypeDescriptor,
  useTypes,
} from '@/api/hooks'
import type { ObjectListItem, TreeNode } from '@/api/types'
import { ErrorState } from '@/components/ErrorState'
import { BulkActionBar, Pagination } from '@/components/patterns/DataControls'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { supportsTemplates } from '@/features/editor/api'
import { AddToGroupDialog } from '@/features/people/AddToGroupDialog'
import { getUserStatus } from '@/features/people/utils'
import type { Scope } from '@/lib/scope'
import { useScope } from '@/lib/scope'
import { BulkEditDialog } from './BulkEditDialog'
import { CopyMoveDialog, type CopyMoveMode } from './CopyMoveDialog'
import { exportToCsv } from './csv'
import { ListingDeleteDialog } from './ListingDeleteDialog'
import { ListingEmptyState } from './ListingEmptyState'
import { ListingHeader } from './ListingHeader'
import { ListingPermissionDenied } from './ListingPermissionDenied'
import { ListingPreviewPanel } from './ListingPreviewPanel'
import { ListingSkeleton } from './ListingSkeleton'
import { ListingTable } from './ListingTable'
import { ListingToolbar } from './ListingToolbar'
import { RestoreDeletedDialog } from './RestoreDeletedDialog'
import { TemplatesView } from './TemplatesView'
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

const VIEW_STORAGE_PREFIX = 'heracles.listing.view.'

export function ObjectListPage({
  type,
  view = 'objects',
}: {
  type: string
  view?: 'objects' | 'templates'
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const desc = useTypeDescriptor(type)
  const types = useTypes()
  const me = useMe()
  const tree = useTree()
  const { base: globalBase, scope: globalScope } = useScope()

  // Saved view (for user list)
  const [savedView, setSavedView] = useState<string>(() => {
    try {
      return localStorage.getItem(`${VIEW_STORAGE_PREFIX}${type}`) || 'all'
    } catch {
      return 'all'
    }
  })

  // State
  const [searchQuery, setSearchQuery] = useState('')
  const debouncedQuery = useDebounced(searchQuery)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [employeeTypes, setEmployeeTypes] = useState<string[]>([])
  const [filterBase, setFilterBase] = useState<string | null>(null)
  const [filterScope, setFilterScope] = useState<Scope>(globalScope)
  const [sorting, setSorting] = useState<SortingState>([])
  const [selection, setSelection] = useState<RowSelectionState>({})
  const [density, setDensity] = useState<Density>(loadDensity)
  const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>(() =>
    loadColumnVisibility(type),
  )

  // Pagination
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)

  const [showPreview, setShowPreview] = useState(false)
  const [previewDn, setPreviewDn] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [singleDeleteTarget, setSingleDeleteTarget] = useState<ObjectListItem | null>(null)
  const [copyMove, setCopyMove] = useState<{ mode: CopyMoveMode; dns: string[] } | null>(null)
  const [bulkEditOpen, setBulkEditOpen] = useState(false)
  const [addToGroupOpen, setAddToGroupOpen] = useState(false)
  const [restoreOpen, setRestoreOpen] = useState(false)

  // Sync saved view change
  const handleSavedViewChange = (v: string) => {
    setSavedView(v)
    try {
      localStorage.setItem(`${VIEW_STORAGE_PREFIX}${type}`, v)
    } catch {
      /* ignore */
    }
    setPage(1)
    if (v === 'active') setStatusFilter('active')
    else if (v === 'locked') setStatusFilter('locked')
    else if (v === 'expiring') setStatusFilter('expired')
    else setStatusFilter('all')
  }

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

  // Reset page when search or filters change
  const filterKey = `${debouncedQuery}:${statusFilter}:${filterBase}:${filterScope}:${employeeTypes.join(',')}`
  const [prevFilterKey, setPrevFilterKey] = useState(filterKey)
  if (prevFilterKey !== filterKey) {
    setPrevFilterKey(filterKey)
    setPage(1)
  }

  // Active query parameters
  const currentBase = filterBase ?? globalBase ?? me.data?.base
  const sort = sorting[0]
  const list = usePaginatedObjectList(type, {
    base: currentBase,
    scope: filterScope,
    q: debouncedQuery || undefined,
    sort: sort?.id,
    order: sort ? (sort.desc ? 'desc' : 'asc') : undefined,
    limit: pageSize,
    offset: (page - 1) * pageSize,
    cursor: btoa(String((page - 1) * pageSize)),
  })

  // Rows and summary
  const rawRows: ObjectListItem[] = useMemo(() => list.data?.items ?? [], [list.data])
  const total = list.data?.total ?? null
  const summary = types.data?.find((x) => x.name === type)
  const label = summary?.label_plural ?? desc.data?.label ?? type

  // Filter rows by status / employee type if active
  const rows = useMemo(() => {
    let r = rawRows
    if (statusFilter !== 'all') {
      if (statusFilter === 'locked') r = r.filter((item) => item.locked)
      else if (statusFilter === 'active') {
        r = r.filter((item) => !item.locked && getUserStatus(item) === 'active')
      } else if (statusFilter === 'expired') {
        r = r.filter((item) => getUserStatus(item) === 'expired')
      }
    }
    if (employeeTypes.length > 0) {
      r = r.filter((item) => employeeTypes.includes(String(item.values.employeeType ?? '')))
    }
    return r
  }, [rawRows, statusFilter, employeeTypes])

  // Items map for easy lookup
  const itemsMap = useMemo(() => {
    const map = new Map<string, ObjectListItem>()
    for (const r of rawRows) map.set(r.dn, r)
    return map
  }, [rawRows])

  // Reset selection on major query/filter changes
  const queryKey = `${type}:${currentBase}:${filterScope}:${debouncedQuery}:${statusFilter}:${page}`
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

  const handleExportCsv = (selectedOnly = false) => {
    if (!desc.data) return
    const exportRows = selectedOnly && selectedDns.length > 0
      ? rawRows.filter((r) => selection[r.dn])
      : rows.length > 0
        ? rows
        : rawRows
    exportToCsv(`${type}-export-${new Date().toISOString().slice(0, 10)}`, desc.data.columns, exportRows)
    toast.success(t('listing.exportCsv'))
  }

  const canCreate = summary?.can_create ?? false
  const hasTemplates = supportsTemplates(desc.data)
  const showTemplates = view === 'templates' && hasTemplates
  const copyMoveItems = copyMove
    ? copyMove.dns.flatMap((dn) => {
        const item = itemsMap.get(dn)
        return item ? [item] : []
      })
    : []

  const currentDepartmentName = findDepartmentLabel(tree.data, currentBase ?? null)
  const hasFilterActive = Boolean(debouncedQuery || statusFilter !== 'all' || employeeTypes.length > 0 || filterBase)

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
        isFetching={list.isFetching}
        onRefresh={() => void list.refetch()}
        onExportCsv={() => handleExportCsv(false)}
        onRestoreDeleted={canCreate ? () => setRestoreOpen(true) : undefined}
      />

      {hasTemplates && (
        <ToggleGroup
          type="single"
          value={showTemplates ? 'templates' : 'objects'}
          onValueChange={(v) => {
            if (v === 'objects' || v === 'templates')
              void navigate({
                to: '/types/$type',
                params: { type },
                search: { view: v === 'templates' ? 'templates' : undefined },
              })
          }}
          aria-label={t('templates.views')}
          className="w-fit"
        >
          <ToggleGroupItem value="objects">{t('templates.viewObjects')}</ToggleGroupItem>
          <ToggleGroupItem value="templates">{t('templates.viewTemplates')}</ToggleGroupItem>
        </ToggleGroup>
      )}

      {showTemplates ? (
        <TemplatesView type={type} typeLabel={desc.data?.label ?? type} canCreate={canCreate} />
      ) : (
        <div className="flex items-start gap-4">
          <div className="min-w-0 flex-1">
            <ListingToolbar
              type={type}
              label={label}
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              currentDepartmentName={currentDepartmentName}
              base={filterBase}
              onBaseChange={setFilterBase}
              scope={filterScope}
              onScopeChange={setFilterScope}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              employeeTypeFilter={employeeTypes}
              onEmployeeTypeFilterChange={setEmployeeTypes}
              savedView={savedView}
              onSavedViewChange={handleSavedViewChange}
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
                  setEmployeeTypes([])
                  setFilterBase(null)
                  setSavedView('all')
                }}
              />
            ) : (
              <>
                <BulkActionBar
                  count={selectedDns.length}
                  onClear={() => setSelection({})}
                >
                  {type === 'user' && (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={lock.isPending}
                        onClick={() => void runLock(selectedDns, true)}
                      >
                        <Lock className="size-4" />
                        {t('listing.lock')}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={lock.isPending}
                        onClick={() => void runLock(selectedDns, false)}
                      >
                        <LockOpen className="size-4" />
                        {t('listing.unlock')}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setAddToGroupOpen(true)}
                      >
                        <Users className="size-4" />
                        {t('peopleUI.bulk.addToGroup')}
                      </Button>
                    </>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setBulkEditOpen(true)}
                  >
                    <Pencil className="size-4" />
                    {t('bulkEdit.action')}
                  </Button>
                  {canCreate && (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setCopyMove({ mode: 'copy', dns: selectedDns })}
                      >
                        <Copy className="size-4" />
                        {t('copy.copyTo')}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setCopyMove({ mode: 'move', dns: selectedDns })}
                      >
                        <FolderInput className="size-4" />
                        {t('copy.moveTo')}
                      </Button>
                    </>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleExportCsv(true)}
                  >
                    <Download className="size-4" />
                    {t('peopleUI.bulk.exportCsv')}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    disabled={del.isPending}
                    onClick={() => setConfirmDelete(true)}
                  >
                    <Trash2 className="size-4" />
                    {t('common.delete')}
                  </Button>
                </BulkActionBar>

                {desc.data && (
                  <div className="overflow-hidden rounded-md border bg-card">
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
                      onCopyTo={canCreate ? (item) => setCopyMove({ mode: 'copy', dns: [item.dn] }) : undefined}
                      onMoveTo={canCreate ? (item) => setCopyMove({ mode: 'move', dns: [item.dn] }) : undefined}
                      selectedRowDn={showPreview ? (previewDn ?? rows[0]?.dn ?? null) : null}
                    />

                    {/* Real Pagination bar */}
                    <div className="border-t border-border bg-card p-3">
                      <Pagination
                        page={page}
                        pageSize={pageSize}
                        total={total ?? rows.length}
                        onPage={setPage}
                        onPageSize={(size) => {
                          setPageSize(size)
                          setPage(1)
                        }}
                        pageSizes={[25, 50, 100]}
                      />
                    </div>
                  </div>
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
      )}

      {/* Delete Confirmation Dialog (bulk) */}
      <ListingDeleteDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        selectedDns={selectedDns}
        itemsMap={itemsMap}
        nameAttr={desc.data?.name_attr}
        onConfirm={() => void runDelete(selectedDns)}
        isDeleting={del.isPending}
      />

      {/* Single Item Delete Dialog */}
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

      <CopyMoveDialog
        open={copyMove !== null}
        onOpenChange={(o) => {
          if (!o) {
            setCopyMove(null)
            setSelection({})
          }
        }}
        mode={copyMove?.mode ?? 'copy'}
        type={type}
        descriptor={desc.data}
        items={copyMoveItems}
      />

      <BulkEditDialog
        open={bulkEditOpen}
        onOpenChange={(o) => {
          setBulkEditOpen(o)
          if (!o) setSelection({})
        }}
        type={type}
        descriptor={desc.data}
        dns={selectedDns}
      />

      <AddToGroupDialog
        open={addToGroupOpen}
        onOpenChange={setAddToGroupOpen}
        userDns={selectedDns}
        onSuccess={() => setSelection({})}
      />

      <RestoreDeletedDialog open={restoreOpen} onOpenChange={setRestoreOpen} type={type} />
    </div>
  )
}

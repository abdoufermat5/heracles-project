import { useNavigate } from '@tanstack/react-router'
import type { ColumnSizingState, RowSelectionState, SortingState } from '@tanstack/react-table'
import {
  Copy,
  Download,
  FolderInput,
  Lock,
  LockOpen,
  MoreHorizontal,
  Pencil,
  Trash2,
  Users,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { supportsTemplates } from '@/features/editor/api'
import { AddToGroupDialog } from '@/features/people/AddToGroupDialog'
import { getUserStatus } from '@/features/people/utils'
import { typeLabel, typeLabelPlural } from '@/lib/labels'
import { useScope } from '@/lib/scope'
import { BulkEditDialog } from './BulkEditDialog'
import { CopyMoveDialog, type CopyMoveMode } from './CopyMoveDialog'
import { exportToCsv } from './csv'
import { buildLdapsearch } from './ldapsearch'
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
  loadColumnOrder,
  loadColumnSizing,
  loadColumnVisibility,
  loadDensity,
  saveColumnOrder,
  saveColumnSizing,
  saveColumnVisibility,
  saveDensity,
  type Density,
  type StatusFilter,
} from './types'
import { DEFAULT_PAGE_SIZE, PAGE_SIZES, statusOfView, useListSearch } from './urlState'

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

export function ObjectListPage({
  type,
  view = 'objects',
  initialView,
}: {
  type: string
  view?: 'objects' | 'templates'
  /** View named by the link (dashboard cards: "locked", "expiring"); it is the status filter. */
  initialView?: string
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const desc = useTypeDescriptor(type)
  const types = useTypes()
  const me = useMe()
  const tree = useTree()
  const { base: globalBase, scope: globalScope } = useScope()

  // The view (filters, sort, page, columns) lives in the URL: shareable, back/forward-safe.
  const { search, update } = useListSearch()
  const [searchQuery, setSearchQuery] = useState(search.q ?? '')
  const debouncedQuery = useDebounced(searchQuery)
  const pushedQuery = useRef(search.q ?? '')
  useEffect(() => {
    // The URL changed under us (back/forward, pasted link): follow it.
    const q = search.q ?? ''
    if (q !== pushedQuery.current) {
      pushedQuery.current = q
      setSearchQuery(q)
    }
  }, [search.q])
  useEffect(() => {
    if (debouncedQuery !== pushedQuery.current) {
      pushedQuery.current = debouncedQuery
      update({ q: debouncedQuery || undefined, page: undefined }, true)
    }
  }, [debouncedQuery, update])

  // The view of the user list is the status filter, kept in the URL (a link may name it).
  const statusFilter: StatusFilter = search.status ?? statusOfView(initialView) ?? 'all'
  const setStatusFilter = (v: StatusFilter) =>
    update({ status: v === 'all' ? undefined : v, filter: undefined, page: undefined })
  const [employeeTypes, setEmployeeTypes] = useState<string[]>([])
  const filterBase = search.base ?? null
  const setFilterBase = (b: string | null) => update({ base: b ?? undefined, page: undefined })
  const filterScope = search.scope ?? globalScope
  const setFilterScope = (sc: 'one' | 'sub') => update({ scope: sc, page: undefined })
  const sorting = useMemo<SortingState>(
    () => (search.sort ? [{ id: search.sort, desc: Boolean(search.desc) }] : []),
    [search.sort, search.desc],
  )
  const setSorting = (next: SortingState) =>
    update({ sort: next[0]?.id, desc: next[0]?.desc || undefined, page: undefined })
  const ldapFilter = search.ldap ?? ''
  const [selection, setSelection] = useState<RowSelectionState>({})
  const [density, setDensity] = useState<Density>(loadDensity)
  const [storedHidden, setColumnVisibility] = useState<Record<string, boolean>>(() =>
    loadColumnVisibility(type),
  )
  // A shared link's `hide` wins over what this browser remembers.
  const columnVisibility = useMemo<Record<string, boolean>>(
    () =>
      search.hide ? Object.fromEntries(search.hide.map((k) => [k, false])) : storedHidden,
    [search.hide, storedHidden],
  )
  const [columnOrder, setColumnOrder] = useState<string[]>(() => loadColumnOrder(type))
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(() =>
    loadColumnSizing(type),
  )

  // Pagination
  const page = search.page ?? 1
  const pageSize = search.size ?? DEFAULT_PAGE_SIZE
  const setPage = (n: number) => update({ page: n })

  const [showPreview, setShowPreview] = useState(false)
  const [previewDn, setPreviewDn] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [singleDeleteTarget, setSingleDeleteTarget] = useState<ObjectListItem | null>(null)
  const [copyMove, setCopyMove] = useState<{ mode: CopyMoveMode; dns: string[] } | null>(null)
  const [bulkEditOpen, setBulkEditOpen] = useState(false)
  const [addToGroupOpen, setAddToGroupOpen] = useState(false)
  const [restoreOpen, setRestoreOpen] = useState(false)

  // Handlers for persistence
  const handleDensityChange = (newDensity: Density) => {
    setDensity(newDensity)
    saveDensity(newDensity)
  }

  const handleToggleColumn = (colKey: string) => {
    const next = { ...columnVisibility, [colKey]: columnVisibility[colKey] === false }
    setColumnVisibility(next)
    saveColumnVisibility(type, next)
    const hidden = Object.keys(next).filter((k) => next[k] === false)
    update({ hide: hidden.length > 0 ? hidden : undefined }, true)
  }

  const handleResetColumns = () => {
    setColumnVisibility({})
    saveColumnVisibility(type, {})
    setColumnOrder([])
    saveColumnOrder(type, [])
    setColumnSizing({})
    saveColumnSizing(type, {})
    update({ hide: undefined }, true)
  }

  const handleMoveColumn = (key: string, direction: -1 | 1) => {
    const keys = (desc.data?.columns ?? []).map((c) => c.key)
    const current = [
      ...columnOrder.filter((k) => keys.includes(k)),
      ...keys.filter((k) => !columnOrder.includes(k)),
    ]
    const i = current.indexOf(key)
    const j = i + direction
    if (i < 0 || j < 0 || j >= current.length) return
    const moved = [...current]
    ;[moved[i], moved[j]] = [moved[j]!, moved[i]!]
    setColumnOrder(moved)
    saveColumnOrder(type, moved)
  }

  const handleColumnSizing = (next: ColumnSizingState) => {
    setColumnSizing(next)
    saveColumnSizing(type, next)
  }

  // Active query parameters
  const currentBase = filterBase ?? globalBase ?? me.data?.base
  const sort = sorting[0]
  const list = usePaginatedObjectList(type, {
    base: currentBase,
    scope: filterScope,
    q: search.q,
    filter: ldapFilter || undefined,
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
  const label = summary
    ? typeLabelPlural(t, summary)
    : desc.data
      ? typeLabelPlural(t, desc.data)
      : type

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
  const queryKey = `${type}:${currentBase}:${filterScope}:${search.q ?? ''}:${ldapFilter}:${statusFilter}:${page}`
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

  const selectedItems = selectedDns.flatMap((dn) => itemsMap.get(dn) ?? [])
  const anySelectedLocked = selectedItems.some((item) => item.locked)
  const anySelectedUnlocked = selectedItems.some((item) => !item.locked)

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

  const handleCopyLdapsearch = () => {
    const cols = desc.data?.columns.map((c) => c.key) ?? []
    const cmd = buildLdapsearch({
      base: currentBase ?? '',
      scope: filterScope,
      typeFilter: desc.data?.ldap_filter,
      extraFilter: ldapFilter || undefined,
      q: search.q,
      searchAttrs: cols,
      attrs: cols,
    })
    void navigator.clipboard?.writeText(cmd)
    toast.success(t('safety.ldapsearchCopied'))
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
  const canEditObjects = summary?.editable !== false
  const canDeleteObjects = summary?.deletable !== false
  const hasTemplates = supportsTemplates(desc.data) && summary?.creatable !== false
  const showTemplates = view === 'templates' && hasTemplates
  const copyMoveItems = copyMove
    ? copyMove.dns.flatMap((dn) => {
        const item = itemsMap.get(dn)
        return item ? [item] : []
      })
    : []

  const currentDepartmentName = findDepartmentLabel(tree.data, currentBase ?? null)
  const hasFilterActive = Boolean(search.q || ldapFilter || statusFilter !== 'all' || employeeTypes.length > 0 || filterBase)

  // Error and permission checks
  // A refused raw filter is shown next to its input, not as a page error.
  const filterError =
    ldapFilter && isApiError(list.error) && list.error.status === 400 ? list.error.message : null
  const primaryError = desc.error ?? (filterError ? null : list.error)
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
        isFetching={list.isFetching}
        onRefresh={() => void list.refetch()}
        onExportCsv={() => handleExportCsv(false)}
        onRestoreDeleted={canCreate ? () => setRestoreOpen(true) : undefined}
        onCopyLdapsearch={handleCopyLdapsearch}
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
        <TemplatesView
          type={type}
          typeLabel={desc.data ? typeLabel(t, desc.data) : type}
          canCreate={canCreate}
        />
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
              availableColumns={desc.data?.columns ?? []}
              columnVisibility={columnVisibility}
              onToggleColumn={handleToggleColumn}
              onResetColumns={handleResetColumns}
              density={density}
              onDensityChange={handleDensityChange}
              showPreview={showPreview}
              onTogglePreview={() => setShowPreview((p) => !p)}
              supportsStatusFilter={type === 'user'}
              ldapFilter={ldapFilter}
              onLdapFilterChange={(f) => update({ ldap: f || undefined, page: undefined })}
              ldapFilterError={filterError}
              columnOrder={columnOrder}
              onMoveColumn={handleMoveColumn}
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
                typeLabel={desc.data ? typeLabel(t, desc.data) : undefined}
                isFiltered={hasFilterActive}
                hasSearch={Boolean(search.q)}
                canCreate={summary?.can_create}
                filterError={filterError}
                onClearLdapFilter={() => update({ ldap: undefined, page: undefined })}
                onClearFilter={() => {
                  setSearchQuery('')
                  setEmployeeTypes([])
                  update({
                    q: undefined,
                    status: undefined,
                    filter: undefined,
                    base: undefined,
                    ldap: undefined,
                    page: undefined,
                  })
                }}
              />
            ) : (
              <>
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
                      columnOrder={columnOrder}
                      columnSizing={columnSizing}
                      onColumnSizingChange={handleColumnSizing}
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
                      onDeleteSingle={canDeleteObjects ? (item) => setSingleDeleteTarget(item) : undefined}
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
                        onPageSize={(size) =>
                          update({
                            size: size === DEFAULT_PAGE_SIZE ? undefined : size,
                            page: undefined,
                          })
                        }
                        pageSizes={PAGE_SIZES}
                      />
                    </div>
                  </div>
                )}

                {/* Below the table: it appears without moving the rows, and sticks to the viewport */}
                <BulkActionBar count={selectedDns.length} onClear={() => setSelection({})}>
                  {type === 'user' && (
                    <>
                      {anySelectedUnlocked && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={lock.isPending}
                          onClick={() => void runLock(selectedDns, true)}
                        >
                          <Lock className="size-4" />
                          {t('listing.lock')}
                        </Button>
                      )}
                      {anySelectedLocked && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={lock.isPending}
                          onClick={() => void runLock(selectedDns, false)}
                        >
                          <LockOpen className="size-4" />
                          {t('listing.unlock')}
                        </Button>
                      )}
                      <Button variant="ghost" size="sm" onClick={() => setAddToGroupOpen(true)}>
                        <Users className="size-4" />
                        {t('peopleUI.bulk.addToGroup')}
                      </Button>
                    </>
                  )}
                  {canEditObjects && (
                    <Button variant="ghost" size="sm" onClick={() => setBulkEditOpen(true)}>
                      <Pencil className="size-4" />
                      {t('bulkEdit.action')}
                    </Button>
                  )}
                  {canDeleteObjects && (
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
                  )}
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t('listingUI.moreActions')}
                        title={t('listingUI.moreActions')}
                      >
                        <MoreHorizontal aria-hidden />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" side="top">
                      {canCreate && (
                        <>
                          <DropdownMenuItem
                            onClick={() => setCopyMove({ mode: 'copy', dns: selectedDns })}
                          >
                            <Copy className="size-4" />
                            {t('copy.copyTo')}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={() => setCopyMove({ mode: 'move', dns: selectedDns })}
                          >
                            <FolderInput className="size-4" />
                            {t('copy.moveTo')}
                          </DropdownMenuItem>
                        </>
                      )}
                      <DropdownMenuItem onClick={() => handleExportCsv(true)}>
                        <Download className="size-4" />
                        {t('peopleUI.bulk.exportCsv')}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </BulkActionBar>
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

import {
  PanelRight,
  Rows3,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { ColumnDescriptor } from '@/api/types'
import { FilterChip } from '@/components/patterns/DataControls'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { Scope } from '@/lib/scope'
import { cn } from '@/lib/utils'
import { DepartmentFilterChip } from './DepartmentFilterChip'
import type { Density, StatusFilter } from './types'

interface ListingToolbarProps {
  type: string
  label: string
  searchQuery: string
  onSearchChange: (q: string) => void
  currentDepartmentName?: string | null
  base?: string | null
  onBaseChange?: (base: string | null) => void
  scope: Scope
  onScopeChange: (scope: Scope) => void
  statusFilter: StatusFilter
  onStatusFilterChange: (status: StatusFilter) => void
  employeeTypeFilter?: string[]
  onEmployeeTypeFilterChange?: (types: string[]) => void
  savedView?: string
  onSavedViewChange?: (view: string) => void
  availableColumns: ColumnDescriptor[]
  columnVisibility: Record<string, boolean>
  onToggleColumn: (key: string) => void
  onResetColumns: () => void
  density: Density
  onDensityChange: (density: Density) => void
  showPreview: boolean
  onTogglePreview: () => void
  supportsStatusFilter?: boolean
}

const segmentClass =
  'inline-flex h-7 items-center rounded-sm px-2.5 text-caption font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring'
const segmentOn = 'bg-card text-foreground shadow-xs'
const segmentOff = 'text-muted-foreground hover:text-foreground'

export function ListingToolbar({
  type,
  label,
  searchQuery,
  onSearchChange,
  base,
  onBaseChange,
  scope,
  onScopeChange,
  statusFilter,
  onStatusFilterChange,
  employeeTypeFilter = [],
  onEmployeeTypeFilterChange,
  savedView = 'all',
  onSavedViewChange,
  availableColumns,
  columnVisibility,
  onToggleColumn,
  onResetColumns,
  density,
  onDensityChange,
  showPreview,
  onTogglePreview,
  supportsStatusFilter = true,
}: ListingToolbarProps) {
  const { t } = useTranslation()
  const searchInputRef = useRef<HTMLInputElement>(null)

  // "/" shortcut to focus search input
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const target = e.target as HTMLElement | null
        const isInputField =
          target?.tagName === 'INPUT' ||
          target?.tagName === 'TEXTAREA' ||
          target?.isContentEditable
        if (!isInputField) {
          e.preventDefault()
          searchInputRef.current?.focus()
          searchInputRef.current?.select()
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const isUser = type === 'user'

  // Options for employee type filter
  const employeeTypeOptions = [
    { value: 'employee', label: 'Employee' },
    { value: 'contractor', label: 'Contractor' },
    { value: 'intern', label: 'Intern' },
  ]

  // Options for status filter chip
  const statusOptions = [
    { value: 'active', label: t('status.active') },
    { value: 'locked', label: t('status.locked') },
    { value: 'expired', label: t('status.expired') },
  ]

  // Status values selected in chip
  const selectedStatuses = statusFilter === 'all' ? [] : [statusFilter]

  return (
    <div className="space-y-3 pb-3">
      {/* 1. Saved views tabs (for users) */}
      {isUser && onSavedViewChange && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-caption font-semibold tracking-[0.06em] uppercase text-muted-foreground mr-1">
            {t('peopleUI.views.savedViews')}:
          </span>
          <div
            role="tablist"
            aria-label={t('peopleUI.views.savedViews')}
            className="inline-flex h-8 items-center gap-0.5 rounded-lg border bg-muted/40 p-1"
          >
            {(
              [
                { id: 'all', label: t('peopleUI.views.all') },
                { id: 'active', label: t('peopleUI.views.active') },
                { id: 'locked', label: t('peopleUI.views.locked') },
                { id: 'expiring', label: t('peopleUI.views.expiring') },
              ] as const
            ).map((v) => (
              <button
                key={v.id}
                role="tab"
                type="button"
                aria-selected={savedView === v.id}
                onClick={() => onSavedViewChange(v.id)}
                className={cn(segmentClass, savedView === v.id ? segmentOn : segmentOff)}
              >
                {v.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 2. Main FilterBar: Search + FilterChips + View controls */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Search input with clear button and "/" shortcut hint */}
        <div className="relative w-full sm:w-72">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            ref={searchInputRef}
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t('listing.searchPlaceholder', { type: label.toLowerCase() })}
            aria-label={t('listing.search')}
            className="h-8 pr-12 pl-8 text-body"
            type="search"
          />
          {searchQuery ? (
            <button
              type="button"
              onClick={() => {
                onSearchChange('')
                searchInputRef.current?.focus()
              }}
              className="absolute top-1/2 right-2 flex size-5 -translate-y-1/2 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
              aria-label={t('listing.clearSearch')}
            >
              <X className="size-3.5" aria-hidden />
            </button>
          ) : (
            <kbd className="pointer-events-none absolute top-1/2 right-2 hidden h-5 -translate-y-1/2 items-center rounded-sm border bg-muted/60 px-1.5 font-mono text-micro font-medium text-muted-foreground select-none sm:inline-flex">
              /
            </kbd>
          )}
        </div>

        {/* Status filter chip */}
        {supportsStatusFilter && (
          <FilterChip
            label={t('peopleUI.filters.status')}
            options={statusOptions}
            selected={selectedStatuses}
            onChange={(vals) => {
              if (vals.length === 0) onStatusFilterChange('all')
              else if (vals.includes('locked')) onStatusFilterChange('locked')
              else if (vals.includes('expired')) onStatusFilterChange('expired')
              else if (vals.includes('active')) onStatusFilterChange('active')
              else onStatusFilterChange('all')
            }}
          />
        )}

        {/* Department picker filter chip */}
        {onBaseChange && (
          <DepartmentFilterChip
            base={base ?? null}
            scope={scope}
            onBaseChange={onBaseChange}
            onScopeChange={onScopeChange}
          />
        )}

        {/* Employee type filter chip */}
        {isUser && onEmployeeTypeFilterChange && (
          <FilterChip
            label={t('peopleUI.filters.employeeType')}
            options={employeeTypeOptions}
            selected={employeeTypeFilter}
            onChange={onEmployeeTypeFilterChange}
          />
        )}

        {/* Right side controls: Columns, Density, Preview */}
        <div className="ml-auto flex items-center gap-1.5">
          {/* Column selector */}
          <DropdownMenu>
            <Tooltip>
              <TooltipTrigger asChild>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    aria-label={t('listing.columns')}
                  >
                    <SlidersHorizontal aria-hidden />
                  </Button>
                </DropdownMenuTrigger>
              </TooltipTrigger>
              <TooltipContent>{t('listing.columns')}</TooltipContent>
            </Tooltip>

            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuLabel className="text-caption font-semibold tracking-[0.06em] uppercase text-muted-foreground">
                {t('listing.columns')}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              {availableColumns.map((col) => {
                const isChecked = columnVisibility[col.key] !== false
                return (
                  <DropdownMenuCheckboxItem
                    key={col.key}
                    checked={isChecked}
                    onCheckedChange={() => onToggleColumn(col.key)}
                  >
                    {col.label}
                  </DropdownMenuCheckboxItem>
                )
              })}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={onResetColumns}
                className="justify-center text-muted-foreground"
              >
                {t('listing.resetColumns')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Density toggle */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="icon-sm"
                onClick={() =>
                  onDensityChange(density === 'comfortable' ? 'compact' : 'comfortable')
                }
                aria-label={
                  density === 'comfortable'
                    ? t('listing.densityCompact')
                    : t('listing.densityComfortable')
                }
              >
                <Rows3
                  className={cn(
                    'transition-transform',
                    density === 'compact' && 'scale-y-75',
                  )}
                  aria-hidden
                />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {density === 'comfortable'
                ? t('listing.densityCompact')
                : t('listing.densityComfortable')}
            </TooltipContent>
          </Tooltip>

          {/* Preview panel toggle */}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={showPreview ? 'secondary' : 'outline'}
                size="icon-sm"
                onClick={onTogglePreview}
                aria-label={showPreview ? t('listing.closePreview') : t('listing.preview')}
              >
                <PanelRight aria-hidden />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {showPreview ? t('listing.closePreview') : t('listing.preview')}
            </TooltipContent>
          </Tooltip>
        </div>
      </div>
    </div>
  )
}

import { useEffect, useRef } from 'react'
import {
  Building2,
  PanelRight,
  Rows3,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ColumnDescriptor } from '@/api/types'
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
import type { Density, StatusFilter } from './types'

interface ListingToolbarProps {
  type: string
  label: string
  searchQuery: string
  onSearchChange: (q: string) => void
  currentDepartmentName?: string | null
  scope: Scope
  onScopeChange: (scope: Scope) => void
  statusFilter: StatusFilter
  onStatusFilterChange: (status: StatusFilter) => void
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
  'inline-flex h-6 items-center rounded-sm px-2 text-caption font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring'
const segmentOn = 'bg-card text-foreground'
const segmentOff = 'text-muted-foreground hover:text-foreground'

export function ListingToolbar({
  label,
  searchQuery,
  onSearchChange,
  currentDepartmentName,
  scope,
  onScopeChange,
  statusFilter,
  onStatusFilterChange,
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

  return (
    <div className="flex h-11 items-center gap-2 overflow-x-auto rounded-t-md border border-b-0 bg-card px-3">
      {/* Search input with clear button and "/" shortcut hint */}
      <div className="relative w-72 max-w-full shrink-0">
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
          className="h-8 pr-14 pl-8 text-body"
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

      {/* Status filter segmented control */}
      {supportsStatusFilter && (
        <div
          role="group"
          aria-label={t('listing.filterStatus')}
          className="inline-flex h-7 shrink-0 items-center gap-0.5 rounded-md border bg-muted/50 p-0.5"
        >
          {(['all', 'active', 'locked'] as const).map((st) => (
            <button
              key={st}
              type="button"
              aria-pressed={statusFilter === st}
              onClick={() => onStatusFilterChange(st)}
              className={cn(segmentClass, statusFilter === st ? segmentOn : segmentOff)}
            >
              {st === 'all'
                ? t('listing.filterAll')
                : st === 'active'
                  ? t('listing.filterActive')
                  : t('listing.filterLocked')}
            </button>
          ))}
        </div>
      )}

      {/* Scope indicator and segmented selector */}
      <div className="flex shrink-0 items-center gap-2">
        {currentDepartmentName && (
          <span
            className="hidden max-w-32 items-center gap-1 truncate text-xs text-muted-foreground md:inline-flex"
            title={currentDepartmentName}
          >
            <Building2 className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate">{currentDepartmentName}</span>
          </span>
        )}
        <div
          role="group"
          aria-label={t('listing.scope')}
          className="inline-flex h-7 items-center gap-0.5 rounded-md border bg-muted/50 p-0.5"
        >
          {(['one', 'sub'] as const).map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={scope === s}
              onClick={() => onScopeChange(s)}
              className={cn(segmentClass, scope === s ? segmentOn : segmentOff)}
            >
              {t(`listing.scope_${s}`)}
            </button>
          ))}
        </div>
      </div>

      {/* Right side controls: Columns, Density, Preview */}
      <div className="ml-auto flex shrink-0 items-center gap-1">
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

        {/* Side preview panel toggle */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant={showPreview ? 'secondary' : 'outline'}
              size="icon-sm"
              onClick={onTogglePreview}
              aria-label={t('listing.preview')}
            >
              <PanelRight aria-hidden />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t('listing.preview')}</TooltipContent>
        </Tooltip>
      </div>
    </div>
  )
}

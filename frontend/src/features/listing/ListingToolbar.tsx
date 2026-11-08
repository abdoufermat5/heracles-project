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
import { Badge } from '@/components/ui/badge'
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
    <div className="flex flex-col gap-3">
      {/* Primary toolbar row */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Search input with debounced clear and "/" shortcut hint */}
        <div className="relative min-w-64 max-w-sm flex-1">
          <Search
            className="text-muted-foreground pointer-events-none absolute top-2.5 left-2.5 size-4"
            aria-hidden
          />
          <Input
            ref={searchInputRef}
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t('listing.searchPlaceholder', { type: label.toLowerCase() })}
            aria-label={t('listing.search')}
            className="h-8 pr-16 pl-8 text-sm"
            type="search"
          />
          {searchQuery ? (
            <button
              type="button"
              onClick={() => {
                onSearchChange('')
                searchInputRef.current?.focus()
              }}
              className="text-muted-foreground hover:text-foreground absolute top-2 right-2 flex size-4 items-center justify-center rounded-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              aria-label={t('listing.clearSearch')}
            >
              <X className="size-3.5" aria-hidden />
            </button>
          ) : (
            <kbd className="text-muted-foreground bg-muted/60 border-border pointer-events-none absolute top-1.5 right-2 hidden h-5 items-center rounded border px-1.5 font-mono text-[10px] font-medium select-none sm:inline-flex">
              /
            </kbd>
          )}
        </div>

        {/* Right side controls: Scope, Columns, Density, Preview */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Scope indicator and selector */}
          <div className="flex items-center gap-1.5">
            {currentDepartmentName && (
              <Badge
                variant="outline"
                className="text-muted-foreground hidden h-8 gap-1.5 border-dashed px-2.5 text-xs font-normal md:inline-flex"
                title={currentDepartmentName}
              >
                <Building2 className="size-3.5 text-muted-foreground" aria-hidden />
                <span className="max-w-28 truncate">{currentDepartmentName}</span>
              </Badge>
            )}

            <div
              role="group"
              aria-label={t('listing.scope')}
              className="bg-muted inline-flex h-8 rounded-md p-0.5"
            >
              {(['one', 'sub'] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={scope === s}
                  onClick={() => onScopeChange(s)}
                  className={cn(
                    'rounded-sm px-2.5 py-1 text-xs font-medium transition-all',
                    scope === s
                      ? 'bg-card text-foreground shadow-xs'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {t(`listing.scope_${s}`)}
                </button>
              ))}
            </div>
          </div>

          {/* Column visibility dropdown */}
          <DropdownMenu>
            <Tooltip>
              <TooltipTrigger asChild>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-1.5 px-2.5 text-xs"
                    aria-label={t('listing.columns')}
                  >
                    <SlidersHorizontal className="size-3.5" aria-hidden />
                    <span className="hidden lg:inline">{t('listing.columns')}</span>
                  </Button>
                </DropdownMenuTrigger>
              </TooltipTrigger>
              <TooltipContent>{t('listing.columns')}</TooltipContent>
            </Tooltip>

            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuLabel className="text-xs font-semibold">
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
                    className="text-xs"
                  >
                    {col.label}
                  </DropdownMenuCheckboxItem>
                )
              })}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={onResetColumns}
                className="text-xs font-medium text-muted-foreground justify-center"
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
                size="sm"
                className="h-8 px-2 text-xs"
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
                    'size-3.5 transition-transform',
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
                size="sm"
                className="h-8 px-2 text-xs"
                onClick={onTogglePreview}
                aria-label={t('listing.preview')}
              >
                <PanelRight className="size-3.5" aria-hidden />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{t('listing.preview')}</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* Filter chips bar (Status: All / Active / Locked) */}
      {supportsStatusFilter && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground font-medium uppercase tracking-wider text-[11px] mr-1">
            {t('listing.filterStatus')}:
          </span>
          {(['all', 'active', 'locked'] as const).map((st) => (
            <button
              key={st}
              type="button"
              onClick={() => onStatusFilterChange(st)}
              className={cn(
                'inline-flex h-6 items-center rounded-full border px-2.5 text-xs font-medium transition-colors',
                statusFilter === st
                  ? 'bg-primary text-primary-foreground border-transparent'
                  : 'bg-card text-muted-foreground border-border hover:bg-accent hover:text-foreground',
              )}
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
    </div>
  )
}

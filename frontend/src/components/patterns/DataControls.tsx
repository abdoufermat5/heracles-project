import { Check, ChevronDown, ChevronLeft, ChevronRight, Search, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/** Search box and filter chips above a list; `end` holds view controls. */
export function FilterBar({
  search,
  onSearch,
  placeholder,
  children,
  end,
  className,
}: {
  search: string
  onSearch: (value: string) => void
  placeholder: string
  children?: React.ReactNode
  end?: React.ReactNode
  className?: string
}) {
  const { t } = useTranslation()
  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      <div className="relative w-full sm:w-72">
        <Search
          className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
          className="pr-8 pl-8"
        />
        {search && (
          <button
            type="button"
            onClick={() => onSearch('')}
            className="absolute top-1/2 right-2 -translate-y-1/2 rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
            aria-label={t('patterns.clearSearch')}
          >
            <X className="size-3.5" />
          </button>
        )}
      </div>
      {children}
      {end && <div className="ml-auto flex items-center gap-2">{end}</div>}
    </div>
  )
}

export interface FilterOption {
  value: string
  label: string
  count?: number
}

/** A filter shown as a chip: "Status: Locked, Expired". Multi-select. */
export function FilterChip({
  label,
  options,
  selected,
  onChange,
}: {
  label: string
  options: FilterOption[]
  selected: string[]
  onChange: (values: string[]) => void
}) {
  const { t } = useTranslation()
  const active = selected.length > 0
  const summary = options
    .filter((o) => selected.includes(o.value))
    .map((o) => o.label)
    .join(', ')
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={cn('border-dashed', active && 'border-solid border-primary/40 bg-primary-soft')}
        >
          <span>{label}</span>
          {active && <span className="max-w-40 truncate font-normal text-primary">{summary}</span>}
          <ChevronDown className="opacity-60" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-52">
        <DropdownMenuLabel>{label}</DropdownMenuLabel>
        {options.map((o) => (
          <DropdownMenuCheckboxItem
            key={o.value}
            checked={selected.includes(o.value)}
            onSelect={(e) => e.preventDefault()}
            onCheckedChange={(on) =>
              onChange(on ? [...selected, o.value] : selected.filter((v) => v !== o.value))
            }
          >
            <span className="flex-1">{o.label}</span>
            {typeof o.count === 'number' && (
              <span className="ml-3 text-caption tabular-nums text-muted-foreground">{o.count}</span>
            )}
          </DropdownMenuCheckboxItem>
        ))}
        {active && (
          <>
            <DropdownMenuSeparator />
            <button
              type="button"
              className="w-full rounded-sm px-2 py-1.5 text-left text-small text-muted-foreground hover:bg-accent hover:text-foreground"
              onClick={() => onChange([])}
            >
              {t('patterns.clearFilter')}
            </button>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** "1–50 of 200", page size and previous / next. */
export function Pagination({
  page,
  pageSize,
  total,
  onPage,
  onPageSize,
  pageSizes = [25, 50, 100],
}: {
  page: number
  pageSize: number
  total: number
  onPage: (page: number) => void
  onPageSize?: (size: number) => void
  pageSizes?: number[]
}) {
  const { t } = useTranslation()
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  return (
    <nav
      aria-label={t('patterns.pagination')}
      className="flex flex-wrap items-center justify-between gap-3 text-small text-muted-foreground"
    >
      <span className="tabular-nums">{t('patterns.range', { from, to, total })}</span>
      <div className="flex items-center gap-3">
        {onPageSize && (
          <label className="flex items-center gap-2">
            <span>{t('patterns.perPage')}</span>
            <select
              className="h-8 rounded-md border border-input bg-card px-2 text-small text-foreground"
              value={pageSize}
              onChange={(e) => onPageSize(Number(e.target.value))}
            >
              {pageSizes.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}
        <span className="tabular-nums">{t('patterns.pageOf', { page, pages })}</span>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
            aria-label={t('patterns.previousPage')}
          >
            <ChevronLeft />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            disabled={page >= pages}
            onClick={() => onPage(page + 1)}
            aria-label={t('patterns.nextPage')}
          >
            <ChevronRight />
          </Button>
        </div>
      </div>
    </nav>
  )
}

/** Appears when rows are selected: "3 selected · Lock · Add to group · …". */
export function BulkActionBar({
  count,
  onClear,
  label,
  children,
}: {
  count: number
  onClear: () => void
  label?: string
  children: React.ReactNode
}) {
  const { t } = useTranslation()
  if (count === 0) return null
  return (
    <div
      role="region"
      aria-label={label ?? t('listing.bulkActions', { defaultValue: t('patterns.bulkActions') })}
      className="sticky bottom-4 z-20 mx-auto mt-3 flex w-fit max-w-full flex-nowrap items-center gap-2 overflow-x-auto rounded-lg border bg-popover px-3 py-2 whitespace-nowrap shadow-overlay [&>*]:shrink-0"
    >
      <span className="flex items-center gap-1.5 pr-2 text-body font-medium">
        <Check className="size-4 text-primary" aria-hidden />
        {t('patterns.selected', { count })}
      </span>
      <span className="h-5 w-px bg-border" aria-hidden />
      {children}
      <Button type="button" variant="ghost" size="sm" onClick={onClear}>
        {t('patterns.clearSelection')}
      </Button>
    </div>
  )
}

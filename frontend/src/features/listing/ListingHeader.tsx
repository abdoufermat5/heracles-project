import { Link } from '@tanstack/react-router'
import { Download, MoreHorizontal, Plus, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { TypeDescriptor, TypeSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { TypeIcon } from '@/lib/icons'

interface ListingHeaderProps {
  type: string
  label: string
  summary?: TypeSummary
  descriptor?: TypeDescriptor
  total: number | null
  isSuccess: boolean
  isFetching: boolean
  onRefresh: () => void
  onExportCsv: () => void
}

export function ListingHeader({
  type,
  label,
  summary,
  descriptor,
  total,
  isSuccess,
  isFetching,
  onRefresh,
  onExportCsv,
}: ListingHeaderProps) {
  const { t } = useTranslation()
  const iconName = summary?.icon ?? descriptor?.icon ?? type

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-4">
      <div className="flex items-center gap-3">
        <div className="bg-primary-soft text-primary flex size-10 items-center justify-center rounded-lg border border-border/80 shadow-xs">
          <TypeIcon name={iconName} className="size-5" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{label}</h1>
          <p className="text-muted-foreground text-sm" aria-live="polite">
            {isSuccess && total !== null
              ? t('listing.count', { count: total })
              : '\u00a0'}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1.5"
          onClick={onRefresh}
          disabled={isFetching}
          aria-label={t('listing.refresh')}
        >
          <RefreshCw className={`size-3.5 ${isFetching ? 'animate-spin' : ''}`} aria-hidden />
          <span className="hidden sm:inline">{t('listing.refresh')}</span>
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="h-8 px-2.5"
              aria-label={t('listing.actions')}
            >
              <MoreHorizontal className="size-4" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem onClick={onExportCsv} className="gap-2">
              <Download className="size-4 text-muted-foreground" aria-hidden />
              <span>{t('listing.exportCsv')}</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        {summary?.can_create && (
          <Button asChild size="sm" className="h-8 gap-1.5 shadow-xs">
            <Link to="/types/$type/new" params={{ type }}>
              <Plus className="size-4" aria-hidden />
              {t('listing.create', { type: descriptor?.label ?? type })}
            </Link>
          </Button>
        )}
      </div>
    </div>
  )
}

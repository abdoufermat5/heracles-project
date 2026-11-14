import { Link } from '@tanstack/react-router'
import { ArchiveRestore, Download, Terminal, MoreHorizontal, Plus, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { TypeDescriptor, TypeSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import { typeLabel } from '@/lib/labels'
import { createLabel } from './types'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

interface ListingHeaderProps {
  type: string
  label: string
  summary?: TypeSummary
  descriptor?: TypeDescriptor
  isFetching: boolean
  onRefresh: () => void
  onExportCsv: () => void
  /** Opens the "restore a deleted object" dialog (needs snapshots). */
  onRestoreDeleted?: () => void
  /** Copies the current view as an `ldapsearch` command. */
  onCopyLdapsearch?: () => void
}

export function ListingHeader({
  type,
  label,
  summary,
  descriptor,
  isFetching,
  onRefresh,
  onExportCsv,
  onRestoreDeleted,
  onCopyLdapsearch,
}: ListingHeaderProps) {
  const { t } = useTranslation()

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 items-baseline gap-3">
        <h1 className="truncate text-lg font-semibold tracking-tight text-foreground">
          {label}
        </h1>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={isFetching}
          aria-label={t('listing.refresh')}
        >
          <RefreshCw className={isFetching ? 'animate-spin' : undefined} aria-hidden />
          <span className="hidden sm:inline">{t('listing.refresh')}</span>
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="icon-sm"
              aria-label={t('listing.actions')}
            >
              <MoreHorizontal aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem onClick={onExportCsv} className="gap-2">
              <Download className="size-3.5 text-muted-foreground" aria-hidden />
              <span>{t('listing.exportCsv')}</span>
            </DropdownMenuItem>
            {onCopyLdapsearch && (
              <DropdownMenuItem onClick={onCopyLdapsearch} className="gap-2">
                <Terminal className="size-3.5 text-muted-foreground" aria-hidden />
                <span>{t('safety.copyLdapsearch')}</span>
              </DropdownMenuItem>
            )}
            {onRestoreDeleted && (
              <DropdownMenuItem onClick={onRestoreDeleted} className="gap-2">
                <ArchiveRestore className="size-3.5 text-muted-foreground" aria-hidden />
                <span>{t('snapshots.deletedAction')}</span>
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>

        {summary?.can_create && (
          <Button asChild size="sm">
            <Link to="/types/$type/new" params={{ type }}>
              <Plus aria-hidden />
              {createLabel(t, type, descriptor ? typeLabel(t, descriptor) : type)}
            </Link>
          </Button>
        )}
      </div>
    </div>
  )
}

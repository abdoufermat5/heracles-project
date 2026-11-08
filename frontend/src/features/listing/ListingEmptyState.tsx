import { Link } from '@tanstack/react-router'
import { Inbox, Plus, SearchX } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

interface ListingEmptyStateProps {
  type: string
  typeLabel?: string
  isFiltered: boolean
  canCreate?: boolean
  onClearFilter: () => void
}

export function ListingEmptyState({
  type,
  typeLabel,
  isFiltered,
  canCreate = false,
  onClearFilter,
}: ListingEmptyStateProps) {
  const { t } = useTranslation()

  if (isFiltered) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-6 py-16 text-center">
        <div className="bg-muted text-muted-foreground flex size-12 items-center justify-center rounded-full">
          <SearchX className="size-6" aria-hidden />
        </div>
        <div>
          <p className="font-semibold text-foreground text-sm">
            {t('listing.noMatches')}
          </p>
          <p className="text-muted-foreground text-xs mt-1">
            {t('listing.noMatchesHelp')}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 text-xs mt-1"
          onClick={onClearFilter}
        >
          {t('listing.clearSearch')}
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-6 py-16 text-center">
      <div className="bg-muted text-muted-foreground flex size-12 items-center justify-center rounded-full">
        <Inbox className="size-6" aria-hidden />
      </div>
      <div>
        <p className="font-semibold text-foreground text-sm">
          {t('listing.empty')}
        </p>
      </div>
      {canCreate && (
        <Button asChild size="sm" className="h-8 gap-1.5 text-xs shadow-xs mt-1">
          <Link to="/types/$type/new" params={{ type }}>
            <Plus className="size-3.5" aria-hidden />
            {t('listing.create', { type: typeLabel ?? type })}
          </Link>
        </Button>
      )}
    </div>
  )
}

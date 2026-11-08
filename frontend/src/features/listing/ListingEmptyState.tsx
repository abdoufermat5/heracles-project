import { Link } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
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
      <div className="flex flex-col items-center justify-center gap-2 rounded-b-md border border-dashed bg-card px-6 py-12 text-center">
        <p className="text-[13px] font-semibold text-foreground">
          {t('listing.noMatches')}
        </p>
        <p className="text-[13px] text-muted-foreground">
          {t('listing.noMatchesHelp')}
        </p>
        <Button variant="outline" size="sm" className="mt-2" onClick={onClearFilter}>
          {t('listing.clearSearch')}
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-b-md border border-dashed bg-card px-6 py-12 text-center">
      <p className="text-[13px] font-semibold text-foreground">{t('listing.empty')}</p>
      {canCreate && (
        <Button asChild size="sm" className="mt-2">
          <Link to="/types/$type/new" params={{ type }}>
            <Plus aria-hidden />
            {t('listing.create', { type: typeLabel ?? type })}
          </Link>
        </Button>
      )}
    </div>
  )
}

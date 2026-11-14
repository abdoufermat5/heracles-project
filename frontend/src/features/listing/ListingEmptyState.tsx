import { Link } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { createLabel } from './types'

interface ListingEmptyStateProps {
  type: string
  typeLabel?: string
  isFiltered: boolean
  /** A search term is part of the active filters. */
  hasSearch?: boolean
  canCreate?: boolean
  onClearFilter: () => void
  /** Server message when the advanced LDAP filter was refused (400). */
  filterError?: string | null
  onClearLdapFilter?: () => void
}

export function ListingEmptyState({
  type,
  typeLabel,
  isFiltered,
  hasSearch = false,
  canCreate = false,
  onClearFilter,
  filterError = null,
  onClearLdapFilter,
}: ListingEmptyStateProps) {
  const { t } = useTranslation()

  if (filterError) {
    return (
      <div
        role="status"
        className="flex flex-col items-center justify-center gap-2 rounded-b-md border border-dashed bg-card px-6 py-12 text-center"
      >
        <p className="text-body font-semibold text-foreground">{t('listing.filterRefusedTitle')}</p>
        <p className="text-body text-muted-foreground">{filterError}</p>
        <Button variant="outline" size="sm" className="mt-2" onClick={onClearLdapFilter ?? onClearFilter}>
          {t('listing.clearLdapFilter')}
        </Button>
      </div>
    )
  }

  if (isFiltered) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-b-md border border-dashed bg-card px-6 py-12 text-center">
        <p className="text-body font-semibold text-foreground">
          {hasSearch ? t('listing.noMatches') : t('listingUI.noMatchesFilters')}
        </p>
        <p className="text-body text-muted-foreground">
          {hasSearch ? t('listing.noMatchesHelp') : t('listingUI.noMatchesFiltersHelp')}
        </p>
        <Button variant="outline" size="sm" className="mt-2" onClick={onClearFilter}>
          {hasSearch ? t('listing.clearSearch') : t('listingUI.clearFilters')}
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-b-md border border-dashed bg-card px-6 py-12 text-center">
      <p className="text-body font-semibold text-foreground">{t('listing.empty')}</p>
      <p className="text-body text-muted-foreground">{t('listingUI.emptyHelp')}</p>
      {canCreate && (
        <Button asChild size="sm" className="mt-2">
          <Link to="/types/$type/new" params={{ type }}>
            <Plus aria-hidden />
            {createLabel(t, type, typeLabel ?? type)}
          </Link>
        </Button>
      )}
    </div>
  )
}

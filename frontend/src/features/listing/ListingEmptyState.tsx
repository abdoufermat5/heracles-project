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
  /** Server message when the advanced LDAP filter was refused (400). */
  filterError?: string | null
  onClearLdapFilter?: () => void
}

export function ListingEmptyState({
  type,
  typeLabel,
  isFiltered,
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
          {t('listing.noMatches')}
        </p>
        <p className="text-body text-muted-foreground">
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
      <p className="text-body font-semibold text-foreground">{t('listing.empty')}</p>
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

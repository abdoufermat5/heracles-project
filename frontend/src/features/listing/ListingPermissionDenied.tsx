import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

interface ListingPermissionDeniedProps {
  onRetry?: () => void
}

export function ListingPermissionDenied({ onRetry }: ListingPermissionDeniedProps) {
  const { t } = useTranslation()

  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center gap-2 rounded-md border bg-card px-6 py-12 text-center"
    >
      <p className="text-body font-semibold text-foreground">
        {t('listing.permissionDenied')}
      </p>
      <p className="max-w-sm text-body text-muted-foreground">
        {t('listing.permissionDeniedDesc')}
      </p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  )
}

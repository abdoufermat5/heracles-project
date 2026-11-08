import { ShieldAlert } from 'lucide-react'
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
      className="flex flex-col items-center justify-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-6 py-16 text-center"
    >
      <div className="bg-destructive/10 text-destructive flex size-12 items-center justify-center rounded-full">
        <ShieldAlert className="size-6" aria-hidden />
      </div>
      <div>
        <p className="font-semibold text-foreground text-sm">
          {t('listing.permissionDenied')}
        </p>
        <p className="text-muted-foreground text-xs mt-1 max-w-sm">
          {t('listing.permissionDeniedDesc')}
        </p>
      </div>
      {onRetry && (
        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 text-xs mt-2"
          onClick={onRetry}
        >
          {t('common.retry')}
        </Button>
      )}
    </div>
  )
}

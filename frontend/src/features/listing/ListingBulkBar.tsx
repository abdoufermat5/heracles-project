import { Lock, LockOpen, Trash2, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

interface ListingBulkBarProps {
  type: string
  selectedCount: number
  onLock?: (doLock: boolean) => void
  onDelete: () => void
  onClearSelection: () => void
  isLocking?: boolean
  isDeleting?: boolean
}

export function ListingBulkBar({
  type,
  selectedCount,
  onLock,
  onDelete,
  onClearSelection,
  isLocking = false,
  isDeleting = false,
}: ListingBulkBarProps) {
  const { t } = useTranslation()

  if (selectedCount === 0) return null

  return (
    <div
      role="region"
      aria-label={t('listing.bulkActions')}
      className="bg-card border-border shadow-md animate-in fade-in-0 slide-in-from-bottom-2 duration-200 sticky bottom-3 z-30 flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-2.5"
    >
      <div className="flex items-center gap-2">
        <span className="bg-primary/10 text-primary flex size-6 items-center justify-center rounded-full text-xs font-semibold">
          {selectedCount}
        </span>
        <span className="text-sm font-medium">
          {t('listing.selected', { count: selectedCount })}
        </span>
      </div>

      <div className="flex items-center gap-2">
        {type === 'user' && onLock && (
          <>
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5 text-xs"
              onClick={() => onLock(true)}
              disabled={isLocking}
            >
              <Lock className="size-3.5" aria-hidden />
              {t('listing.lock')}
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5 text-xs"
              onClick={() => onLock(false)}
              disabled={isLocking}
            >
              <LockOpen className="size-3.5" aria-hidden />
              {t('listing.unlock')}
            </Button>
          </>
        )}

        <Button
          size="sm"
          variant="destructive"
          className="h-8 gap-1.5 text-xs"
          onClick={onDelete}
          disabled={isDeleting}
        >
          <Trash2 className="size-3.5" aria-hidden />
          {t('common.delete')}
        </Button>

        <Button
          size="sm"
          variant="ghost"
          className="h-8 px-2 text-muted-foreground hover:text-foreground"
          onClick={onClearSelection}
          aria-label={t('listing.clearSelection')}
        >
          <X className="size-4" aria-hidden />
        </Button>
      </div>
    </div>
  )
}

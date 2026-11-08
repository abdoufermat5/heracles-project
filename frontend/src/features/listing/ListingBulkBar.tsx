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

const darkGhost =
  'text-primary-foreground/80 hover:bg-primary-foreground/10 hover:text-primary-foreground'

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
      className="flex h-11 items-center justify-between gap-3 border-x border-primary bg-primary px-3 text-primary-foreground"
    >
      <span className="text-[13px] font-medium tabular-nums">
        {t('listing.selected', { count: selectedCount })}
      </span>

      <div className="flex items-center gap-1">
        {type === 'user' && onLock && (
          <>
            <Button
              size="sm"
              variant="ghost"
              className={darkGhost}
              onClick={() => onLock(true)}
              disabled={isLocking}
            >
              <Lock className="size-3.5" aria-hidden />
              {t('listing.lock')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className={darkGhost}
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
          variant="ghost"
          className="text-primary-foreground/80 hover:bg-destructive/30 hover:text-primary-foreground"
          onClick={onDelete}
          disabled={isDeleting}
        >
          <Trash2 className="size-3.5" aria-hidden />
          {t('common.delete')}
        </Button>

        <Button
          size="icon-sm"
          variant="ghost"
          className={darkGhost}
          onClick={onClearSelection}
          aria-label={t('listing.clearSelection')}
        >
          <X aria-hidden />
        </Button>
      </div>
    </div>
  )
}

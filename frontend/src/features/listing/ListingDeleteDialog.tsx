import { useTranslation } from 'react-i18next'
import type { ObjectListItem } from '@/api/types'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

interface ListingDeleteDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  selectedDns: string[]
  itemsMap?: Map<string, ObjectListItem>
  nameAttr?: string
  onConfirm: () => void
  isDeleting?: boolean
}

export function ListingDeleteDialog({
  open,
  onOpenChange,
  selectedDns,
  itemsMap,
  nameAttr,
  onConfirm,
  isDeleting = false,
}: ListingDeleteDialogProps) {
  const { t } = useTranslation()
  const count = selectedDns.length
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-lead">
            {t('listing.deleteTitle', { count })}
          </AlertDialogTitle>
          <AlertDialogDescription className="space-y-2 text-left text-body">
            <span>{t('listing.deleteConfirmDesc')}</span>
            <div className="max-h-48 overflow-y-auto rounded-sm border bg-muted/40 p-2">
              <ul className="space-y-1">
                {selectedDns.map((dn) => {
                  const item = itemsMap?.get(dn)
                  const displayName = nameAttr && item?.values[nameAttr]
                    ? String(item.values[nameAttr])
                    : dn
                  return (
                    <li key={dn} className="font-mono text-small text-foreground" title={dn}>
                      <span className="block truncate">{displayName}</span>
                      {displayName !== dn && (
                        <span className="block truncate text-caption text-muted-foreground">{dn}</span>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
            <p className="pt-1 text-small font-medium text-destructive">
              {t('editor.deleteBody')}
            </p>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isDeleting}>
            {t('common.cancel')}
          </AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={onConfirm}
            disabled={isDeleting}
          >
            {isDeleting ? t('common.loading') : t('common.delete')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

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
  const previewLimit = 8
  const previewDns = selectedDns.slice(0, previewLimit)
  const remainingCount = count - previewDns.length

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-[15px]">
            {t('listing.deleteTitle', { count })}
          </AlertDialogTitle>
          <AlertDialogDescription className="space-y-2 text-left text-[13px]">
            <span>{t('listing.deleteConfirmDesc')}</span>
            <div className="max-h-48 overflow-y-auto rounded-sm border bg-muted/40 p-2">
              <ul className="space-y-1">
                {previewDns.map((dn) => {
                  const item = itemsMap?.get(dn)
                  const displayName = nameAttr && item?.values[nameAttr]
                    ? String(item.values[nameAttr])
                    : dn
                  return (
                    <li key={dn} className="truncate font-mono text-[12px] text-foreground">
                      {displayName}
                    </li>
                  )
                })}
              </ul>
              {remainingCount > 0 && (
                <p className="mt-2 text-muted-foreground">
                  {t('listing.andMore', { count: remainingCount })}
                </p>
              )}
            </div>
            <p className="pt-1 text-[12px] font-medium text-destructive">
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

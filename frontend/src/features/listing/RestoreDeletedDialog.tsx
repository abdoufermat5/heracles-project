import { ArchiveRestore } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/ErrorState'
import { useDeletedSnapshots, useRestoreSnapshot } from '@/features/editor/api'
import { formatDateTime, rdnValue } from '@/lib/objects'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  type: string
}

/** Objects that no longer exist but have a snapshot: restore them from the listing. */
export function RestoreDeletedDialog({ open, onOpenChange, type }: Props) {
  const { t, i18n } = useTranslation()
  const deleted = useDeletedSnapshots(type, open)
  const restore = useRestoreSnapshot(type)

  const doRestore = async (id: string) => {
    try {
      await restore.mutateAsync(id)
      toast.success(t('snapshots.deletedRestored'))
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="text-lead">{t('snapshots.deletedTitle')}</DialogTitle>
          <DialogDescription className="text-body">{t('snapshots.deletedHelp')}</DialogDescription>
        </DialogHeader>

        {deleted.isError ? (
          <ErrorState error={deleted.error} onRetry={() => void deleted.refetch()} />
        ) : !deleted.data ? (
          <div className="space-y-2" aria-busy="true" aria-label={t('common.loading')}>
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
        ) : deleted.data.length === 0 ? (
          <EmptyState icon={<ArchiveRestore aria-hidden />} title={t('snapshots.deletedEmpty')} className="border-0 py-8" />
        ) : (
          <ul className="max-h-80 divide-y overflow-y-auto rounded-md border" aria-label={t('snapshots.deletedObject')}>
            {deleted.data.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-body font-medium text-foreground" title={s.object_dn}>
                    {rdnValue(s.object_dn ?? s.id)}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {formatDateTime(s.created_at, i18n.language)}
                    {s.description ? ` — ${s.description}` : ''}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={restore.isPending}
                  onClick={() => void doRestore(s.id)}
                  aria-label={`${t('snapshots.deletedRestore')} ${rdnValue(s.object_dn ?? s.id)}`}
                >
                  <ArchiveRestore aria-hidden />
                  {t('snapshots.deletedRestore')}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}

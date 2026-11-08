import { Lock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { LockInfo } from '@/api/types'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'

export function LockedDialog({ lock, onClose }: { lock: LockInfo | null; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const since = lock ? new Date(lock.since) : null
  const when =
    since && !Number.isNaN(since.getTime())
      ? new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }).format(since)
      : (lock?.since ?? '')
  return (
    <AlertDialog open={lock !== null} onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2 text-[15px]">
            <Lock className="size-4 text-warning" aria-hidden />
            {t('editor.lockedTitle')}
          </AlertDialogTitle>
          <AlertDialogDescription className="text-[13px]">
            {t('editor.lockedBody', { user: lock?.user ?? '', since: when })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogAction onClick={onClose}>{t('common.ok')}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

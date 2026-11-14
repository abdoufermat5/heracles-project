import { Camera, History, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
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
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ErrorState } from '@/components/ErrorState'
import { snapshotDescription } from '@/features/people/utils'
import { formatDateTime } from '@/lib/objects'
import { useSnapshotMutations, useSnapshots, type SnapshotEntry } from './api'

interface Props {
  type: string
  dn: string
  /** Called after a snapshot was restored (the editor reloads the object). */
  onRestored: () => void
}

/** Snapshots of one object: list, take, restore (confirmed) and delete (confirmed). */
export function SnapshotsPanel({ type, dn, onRestored }: Props) {
  const { t, i18n } = useTranslation()
  const snaps = useSnapshots(type, dn)
  const { create, restore, remove } = useSnapshotMutations(type, dn)
  const [description, setDescription] = useState('')
  const [toRestore, setToRestore] = useState<SnapshotEntry | null>(null)
  const [toDelete, setToDelete] = useState<SnapshotEntry | null>(null)

  const fail = (e: unknown) => toast.error(isApiError(e) ? e.message : t('common.error'))

  const take = async () => {
    try {
      await create.mutateAsync(description.trim())
      setDescription('')
      toast.success(t('snapshots.taken'))
    } catch (e) {
      fail(e)
    }
  }
  const doRestore = async () => {
    if (!toRestore) return
    try {
      await restore.mutateAsync(toRestore.id)
      toast.success(t('snapshots.restored'))
      onRestored()
    } catch (e) {
      fail(e)
    } finally {
      setToRestore(null)
    }
  }
  const doDelete = async () => {
    if (!toDelete) return
    try {
      await remove.mutateAsync(toDelete.id)
      toast.success(t('snapshots.deleted'))
    } catch (e) {
      fail(e)
    } finally {
      setToDelete(null)
    }
  }

  return (
    <section aria-labelledby="snaps-title" className="rounded-md border bg-card">
      <div className="border-b px-4 py-3">
        <h2 id="snaps-title" className="text-body font-semibold text-foreground">
          {t('snapshots.title')}
        </h2>
        <p className="text-xs text-muted-foreground">{t('snapshots.help')}</p>
      </div>

      {/* Not a <form>: this panel renders inside the editor's own form, and nested
          forms make the browser submit the outer one (a full page reload). */}
      <div className="flex flex-wrap items-end gap-2 border-b px-4 py-3">
        <div className="min-w-56 flex-1 space-y-1.5">
          <Label htmlFor="snapshot-description" className="text-xs font-medium text-muted-foreground">
            {t('snapshots.descriptionLabel')}
          </Label>
          <Input
            id="snapshot-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                void take()
              }
            }}
            placeholder={t('snapshots.descriptionPlaceholder')}
            className="h-8 text-body"
          />
        </div>
        <Button type="button" size="sm" onClick={() => void take()} disabled={create.isPending}>
          <Camera aria-hidden />
          {t('snapshots.take')}
        </Button>
      </div>

      {snaps.isError ? (
        <div className="p-4">
          <ErrorState error={snaps.error} onRetry={() => void snaps.refetch()} />
        </div>
      ) : !snaps.data ? (
        <div className="space-y-2 p-4" aria-busy="true" aria-label={t('common.loading')}>
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-2/3" />
        </div>
      ) : snaps.data.length === 0 ? (
        <div className="p-4">
          <EmptyState icon={<History aria-hidden />} title={t('snapshots.empty')} className="border-0 py-8" />
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('snapshots.columnDate')}</TableHead>
              <TableHead>{t('snapshots.columnDescription')}</TableHead>
              <TableHead>{t('snapshots.columnSource')}</TableHead>
              <TableHead className="w-0">
                <span className="sr-only">{t('editor.actions')}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {snaps.data.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="whitespace-nowrap tabular-nums">
                  {formatDateTime(s.created_at, i18n.language)}
                </TableCell>
                <TableCell>{snapshotDescription(t, s.description)}</TableCell>
                <TableCell className="text-muted-foreground">{s.source ?? t('snapshots.noDescription')}</TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-1">
                    <Button type="button" variant="outline" size="sm" onClick={() => setToRestore(s)}>
                      <History aria-hidden />
                      {t('snapshots.restore')}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      className="text-muted-foreground hover:text-destructive"
                      onClick={() => setToDelete(s)}
                      aria-label={t('snapshots.delete')}
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <AlertDialog open={toRestore !== null} onOpenChange={(o) => !o && setToRestore(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lead font-semibold">{t('snapshots.restoreTitle')}</AlertDialogTitle>
            <AlertDialogDescription className="text-body text-muted-foreground">
              {t('snapshots.restoreBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={() => void doRestore()}>{t('snapshots.restore')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={toDelete !== null} onOpenChange={(o) => !o && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lead font-semibold">{t('snapshots.deleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription className="text-body text-muted-foreground">
              {t('snapshots.deleteBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void doDelete()}>
              {t('snapshots.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

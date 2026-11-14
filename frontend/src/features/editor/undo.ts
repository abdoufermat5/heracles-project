import { useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { qk } from '@/api/hooks'
import { objectsApi } from './api'

/** How long the Undo action stays on the success toast. */
export const UNDO_WINDOW_MS = 10_000

/**
 * Undo for saves. Heracles does not snapshot on its own, so just before a save an undo
 * point is taken (a snapshot); when snapshots are off or refused no point exists and the
 * toast carries no Undo action.
 */
export function useUndoableSave(type: string) {
  const { t } = useTranslation()
  const qc = useQueryClient()

  /** Takes the undo point; resolves to its id, or null when none could be taken. */
  const takeUndoPoint = useCallback(
    async (dn: string): Promise<string | null> => {
      try {
        const snap = await objectsApi.createSnapshot(type, dn, 'Before edit (undo point)')
        void qc.invalidateQueries({ queryKey: qk.snapshots(type, dn) })
        return snap.id
      } catch {
        return null
      }
    },
    [qc, type],
  )

  /** Success toast; with `snapshotId` it offers Undo for ten seconds. */
  const toastSaved = useCallback(
    (message: string, snapshotId: string | null, onUndone?: () => void) => {
      if (!snapshotId) {
        toast.success(message)
        return
      }
      toast.success(message, {
        duration: UNDO_WINDOW_MS,
        action: {
          label: t('safety.undo'),
          onClick: () => {
            void objectsApi
              .restoreSnapshot(snapshotId)
              .then(() => {
                void qc.invalidateQueries({ queryKey: qk.objects(type) })
                toast.success(t('safety.undone'))
                onUndone?.()
              })
              .catch(() => toast.error(t('safety.undoFailed')))
          },
        },
      })
    },
    [qc, t, type],
  )

  return { takeUndoPoint, toastSaved }
}

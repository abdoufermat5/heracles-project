import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
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
import { ReauthDialog } from './ReauthDialog'

/**
 * Administrator action "sign this user out everywhere", for the `…` menu of a user profile.
 * Mount it with the person's DN and a display name; the caller owns `open`. The server needs
 * the right to lock the account and a recent confirmation (asked here when missing).
 */
export function RevokeUserSessionsDialog({
  dn,
  name,
  open,
  onOpenChange,
}: {
  dn: string
  name: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const [needsReauth, setNeedsReauth] = useState(false)
  const revoke = useMutation({
    mutationFn: () => api.revokeUserSessions(dn),
    onSuccess: (r) => {
      toast.success(t('sessions.admin.done', { count: r.revoked }))
      onOpenChange(false)
    },
    onError: (e) => {
      if (isApiError(e) && e.code === 'reauth_required') setNeedsReauth(true)
      else toast.error(isApiError(e) ? e.message : t('sessions.failed'))
    },
  })

  return (
    <>
      <AlertDialog open={open && !needsReauth} onOpenChange={onOpenChange}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lead">
              {t('sessions.admin.title', { name })}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-body">
              {t('sessions.admin.body')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('sessions.admin.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={revoke.isPending}
              onClick={(e) => {
                e.preventDefault()
                revoke.mutate()
              }}
            >
              {t('sessions.admin.confirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <ReauthDialog
        open={open && needsReauth}
        body={t('reauth.adminBody')}
        onCancel={() => {
          setNeedsReauth(false)
          onOpenChange(false)
        }}
        onConfirmed={() => {
          setNeedsReauth(false)
          revoke.mutate()
        }}
      />
    </>
  )
}

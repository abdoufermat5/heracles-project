import { KeyRound, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { ErrorState } from '@/components/ErrorState'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useRoleMutations, useRoles } from './hooks'
import { RoleEditor } from './RoleEditor'
import type { AclRole } from './types'

export function RolesPanel() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = useRoles()
  const { remove } = useRoleMutations()
  const [editing, setEditing] = useState<AclRole | null | undefined>(undefined)
  const [deleting, setDeleting] = useState<AclRole | null>(null)

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />

  const confirmDelete = async () => {
    if (!deleting) return
    try {
      await remove.mutateAsync({ dn: deleting.dn, force: (deleting.used_by ?? 0) > 0 })
      toast.success(t('acl.roleDeleted'))
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
    setDeleting(null)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[13px] text-muted-foreground">{t('acl.rolesHelp')}</p>
        <Button size="sm" onClick={() => setEditing(null)}>
          <Plus />
          {t('acl.newRole')}
        </Button>
      </div>

      {isPending ? (
        <Skeleton className="h-32 w-full" />
      ) : data.length === 0 ? (
        <EmptyState
          icon={<KeyRound />}
          title={t('acl.noRoles')}
          description={t('acl.noRolesHelp')}
        />
      ) : (
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('acl.name')}</TableHead>
                <TableHead>{t('acl.description')}</TableHead>
                <TableHead className="text-right">{t('acl.usedBy')}</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((r) => (
                <TableRow key={r.dn}>
                  <TableCell>
                    <button
                      type="button"
                      className="font-medium underline-offset-2 hover:underline focus-visible:underline"
                      onClick={() => setEditing(r)}
                    >
                      {r.cn}
                    </button>
                    <div className="font-dn text-[11px] text-muted-foreground">{r.dn}</div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{r.description || '—'}</TableCell>
                  <TableCell className="text-right">
                    <Badge variant={(r.used_by ?? 0) > 0 ? 'secondary' : 'outline'}>
                      {r.used_by ?? 0}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t('acl.editRole', { name: r.cn })}
                      onClick={() => setEditing(r)}
                    >
                      <Pencil />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t('acl.deleteRole', { name: r.cn })}
                      onClick={() => setDeleting(r)}
                    >
                      <Trash2 />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {editing !== undefined && (
        <RoleEditor
          key={editing?.dn ?? 'new'}
          open
          role={editing}
          onOpenChange={(o) => {
            if (!o) setEditing(undefined)
          }}
        />
      )}

      <AlertDialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('acl.deleteRole', { name: deleting?.cn ?? '' })}</AlertDialogTitle>
            <AlertDialogDescription>
              {(deleting?.used_by ?? 0) > 0
                ? t('acl.deleteRoleInUse', { count: deleting?.used_by ?? 0 })
                : t('acl.deleteRoleConfirm')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={() => void confirmDelete()}>{t('common.delete')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

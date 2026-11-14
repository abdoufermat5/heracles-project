import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Users } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '@/api/endpoints'
import { useObjectList } from '@/api/hooks'
import type { ObjectListItem } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useReferences } from '@/features/editor/api'

interface AddToGroupDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  userDns: string[]
  userName?: string
  onSuccess?: (groupName: string) => void
}

export function AddToGroupDialog({
  open,
  onOpenChange,
  userDns,
  userName,
  onSuccess,
}: AddToGroupDialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [selectedGroupDn, setSelectedGroupDn] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)

  // Load available groups
  const groupsQuery = useObjectList('group', { scope: 'sub', limit: 100 })
  const allGroups: ObjectListItem[] = groupsQuery.data?.pages.flatMap((p) => p.items) ?? []
  // A single person: offer only the groups they are not in yet.
  const single = userDns.length === 1 ? (userDns[0] ?? '') : ''
  const referencesQuery = useReferences('user', single, open && single !== '')
  const memberOf = new Set(
    (referencesQuery.data ?? []).filter((r) => r.type === 'group').map((r) => r.dn.toLowerCase()),
  )
  const groups = allGroups.filter((g) => !memberOf.has(g.dn.toLowerCase()))

  const isBulk = userDns.length > 1
  const title = isBulk
    ? t('peopleUI.bulk.addToGroupTitle', { count: userDns.length })
    : t('peopleUI.userProfile.addToGroupDialog.title', { name: userName ?? 'User' })

  const description = isBulk
    ? t('peopleUI.bulk.addToGroupDesc')
    : t('peopleUI.userProfile.addToGroupDialog.description')

  const handleConfirm = async () => {
    if (!selectedGroupDn || userDns.length === 0) return
    setSubmitting(true)
    try {
      const groupObj = await api.getObject('group', selectedGroupDn)
      const currentMembersRaw = groupObj.tabs.main?.values.member
      const currentMembers: string[] = Array.isArray(currentMembersRaw)
        ? (currentMembersRaw as string[])
        : typeof currentMembersRaw === 'string' && currentMembersRaw
          ? [currentMembersRaw]
          : []

      const currentLower = new Set(currentMembers.map((m) => m.toLowerCase()))
      const toAdd = userDns.filter((dn) => !currentLower.has(dn.toLowerCase()))

      const groupName = String(
        groupObj.tabs.main?.values.cn ??
          groups.find((g) => g.dn.toLowerCase() === selectedGroupDn.toLowerCase())?.values.cn ??
          'group',
      )

      if (toAdd.length === 0) {
        toast.info(t('peopleUI.userProfile.addToGroupDialog.alreadyMember'))
        onOpenChange(false)
        return
      }

      const updatedMembers = [...currentMembers, ...toAdd]
      await api.patchObject('group', selectedGroupDn, {
        tabs: {
          main: {
            active: true,
            values: { member: updatedMembers },
          },
        },
      })

      // Invalidate queries so lists and references update
      void queryClient.invalidateQueries({ queryKey: ['objects', 'group'] })
      void queryClient.invalidateQueries({ queryKey: ['references'] })
      void queryClient.invalidateQueries({ queryKey: ['objects', 'user'] })

      const successMsg = isBulk
        ? t('peopleUI.bulk.addToGroupSuccess', { count: userDns.length, group: groupName })
        : t('peopleUI.userProfile.addToGroupDialog.success', { group: groupName })

      toast.success(successMsg)
      onSuccess?.(groupName)
      onOpenChange(false)
      setSelectedGroupDn('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('peopleUI.errors.addToGroup'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Users className="size-5 text-primary" aria-hidden />
            <span>{title}</span>
          </DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <label className="grid gap-1.5 text-small font-medium text-foreground">
            <span>{t('peopleUI.userProfile.addToGroupDialog.groupLabel')}</span>
            {groups.length === 0 && !groupsQuery.isPending ? (
              <p className="text-small text-muted-foreground">
                {t('peopleUI.userProfile.addToGroupDialog.noGroups')}
              </p>
            ) : (
              <Select value={selectedGroupDn} onValueChange={setSelectedGroupDn}>
                <SelectTrigger className="w-full">
                  <SelectValue
                    placeholder={
                      groupsQuery.isPending
                        ? t('common.loading')
                        : t('peopleUI.userProfile.addToGroupDialog.selectPlaceholder')
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {groups.map((g) => {
                    const name = String(g.values.cn ?? g.dn)
                    const desc = g.values.description ? String(g.values.description) : null
                    return (
                      <SelectItem key={g.dn} value={g.dn}>
                        <div className="flex flex-col text-left">
                          <span className="font-medium text-foreground">{name}</span>
                          {desc && (
                            <span className="text-caption text-muted-foreground">{desc}</span>
                          )}
                        </div>
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
            )}
          </label>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={submitting}
            onClick={() => onOpenChange(false)}
          >
            {t('common.cancel')}
          </Button>
          <Button
            type="button"
            disabled={!selectedGroupDn || submitting}
            onClick={() => void handleConfirm()}
          >
            {submitting && <Loader2 className="animate-spin" aria-hidden />}
            {t('peopleUI.userProfile.addToGroupDialog.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

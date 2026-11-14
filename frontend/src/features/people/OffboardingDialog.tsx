import { useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  Camera,
  CheckCircle2,
  FolderInput,
  Loader2,
  Lock,
  UserMinus,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '@/api/endpoints'
import { useTree } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { orgPath } from '@/lib/dn'
import { flattenDepartments } from './utils'

interface OffboardingDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: {
    dn: string
    cn: string
    uid: string
    base?: string
  }
  groups: Array<{ dn: string; name: string }>
  onSuccess?: () => void
}

export function OffboardingDialog({
  open,
  onOpenChange,
  user,
  groups,
  onSuccess,
}: OffboardingDialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const tree = useTree()

  const [takeSnapshot, setTakeSnapshot] = useState(true)
  const [snapshotDesc, setSnapshotDesc] = useState(() =>
    t('peopleUI.offboarding.snapshotDescription', { login: user.uid }),
  )
  const [lockAccount, setLockAccount] = useState(true)
  const [selectedGroups, setSelectedGroups] = useState<string[]>(() =>
    groups.map((g) => g.dn),
  )
  const [moveAccount, setMoveAccount] = useState(false)
  const [targetDept, setTargetDept] = useState<string>('')

  const [submitting, setSubmitting] = useState(false)
  const [completed, setCompleted] = useState(false)
  const [results, setResults] = useState<{
    snapshot: boolean
    locked: boolean
    groupsRemoved: number
    movedTo: string | null
  }>({
    snapshot: false,
    locked: false,
    groupsRemoved: 0,
    movedTo: null,
  })

  const topLevel = t('patterns.topLevel')
  const deptList = tree.data ? flattenDepartments(tree.data, topLevel) : []
  const userCurrentDept = user.base ? orgPath(user.base).join(' › ') : orgPath(user.dn).join(' › ')

  const handleToggleGroup = (dn: string) => {
    setSelectedGroups((prev) =>
      prev.includes(dn) ? prev.filter((x) => x !== dn) : [...prev, dn],
    )
  }

  const handleExecute = async () => {
    setSubmitting(true)
    let snapshotDone = false
    let lockDone = false
    let groupsDone = 0
    let movedDone: string | null = null

    try {
      // 1. Take safety snapshot
      if (takeSnapshot) {
        try {
          await api.createSnapshot('user', user.dn, snapshotDesc)
          snapshotDone = true
        } catch (e) {
          console.error('Failed to create snapshot', e)
        }
      }

      // 2. Lock account
      if (lockAccount) {
        try {
          await api.lockAccount(user.dn)
          lockDone = true
        } catch (e) {
          console.error('Failed to lock account', e)
        }
      }

      // 3. Remove group memberships
      for (const groupDn of selectedGroups) {
        try {
          const groupObj = await api.getObject('group', groupDn)
          const currentMembersRaw = groupObj.tabs.main?.values.member
          const currentMembers: string[] = Array.isArray(currentMembersRaw)
            ? (currentMembersRaw as string[])
            : typeof currentMembersRaw === 'string' && currentMembersRaw
              ? [currentMembersRaw]
              : []

          const updated = currentMembers.filter(
            (m) => m.toLowerCase() !== user.dn.toLowerCase(),
          )
          await api.patchObject('group', groupDn, {
            tabs: {
              main: {
                active: true,
                values: { member: updated },
              },
            },
          })
          groupsDone++
        } catch (e) {
          console.error(`Failed to remove from group ${groupDn}`, e)
        }
      }

      // 4. Optionally move to archive department
      if (moveAccount && targetDept) {
        try {
          await api.moveObject('user', user.dn, targetDept)
          const deptLabel = deptList.find((d) => d.dn === targetDept)?.label ?? targetDept
          movedDone = deptLabel
        } catch (e) {
          console.error('Failed to move account', e)
        }
      }

      setResults({
        snapshot: snapshotDone,
        locked: lockDone,
        groupsRemoved: groupsDone,
        movedTo: movedDone,
      })

      // Invalidate caches
      void queryClient.invalidateQueries({ queryKey: ['objects', 'user'] })
      void queryClient.invalidateQueries({ queryKey: ['references'] })
      void queryClient.invalidateQueries({ queryKey: ['objects', 'group'] })
      void queryClient.invalidateQueries({ queryKey: ['snapshots'] })

      setCompleted(true)
      onSuccess?.()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('peopleUI.errors.offboarding'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = () => {
    onOpenChange(false)
    setCompleted(false)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => (!submitting ? onOpenChange(o) : undefined)}>
      <DialogContent className="sm:max-w-lg">
        {completed ? (
          // Completion summary view
          <div className="space-y-5 py-2">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="size-8 text-success shrink-0" aria-hidden />
              <div>
                <DialogTitle className="text-lead font-semibold">
                  {t('peopleUI.offboarding.summaryTitle')}
                </DialogTitle>
                <DialogDescription>
                  {t('peopleUI.offboarding.summaryDesc', { name: user.cn })}
                </DialogDescription>
              </div>
            </div>

            <div className="space-y-2.5 rounded-lg border bg-muted/30 p-4 text-small">
              {results.snapshot && (
                <div className="flex items-center gap-2 text-foreground">
                  <CheckCircle2 className="size-4 text-success" />
                  <span>{t('peopleUI.offboarding.snapshotCreated')}</span>
                </div>
              )}
              {results.locked && (
                <div className="flex items-center gap-2 text-foreground">
                  <CheckCircle2 className="size-4 text-success" />
                  <span>{t('peopleUI.offboarding.accountLocked')}</span>
                </div>
              )}
              {results.groupsRemoved > 0 && (
                <div className="flex items-center gap-2 text-foreground">
                  <CheckCircle2 className="size-4 text-success" />
                  <span>
                    {t('peopleUI.offboarding.groupsRemoved', { count: results.groupsRemoved })}
                  </span>
                </div>
              )}
              {results.movedTo && (
                <div className="flex items-center gap-2 text-foreground">
                  <CheckCircle2 className="size-4 text-success" />
                  <span>
                    {t('peopleUI.offboarding.userMoved', { dept: results.movedTo })}
                  </span>
                </div>
              )}
            </div>

            <DialogFooter>
              <Button type="button" onClick={handleClose}>
                {t('peopleUI.offboarding.close')}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          // Configuration view
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-warning">
                <UserMinus className="size-5 shrink-0" aria-hidden />
                <span>{t('peopleUI.offboarding.dialogTitle', { name: user.cn })}</span>
              </DialogTitle>
              <DialogDescription>
                {t('peopleUI.offboarding.dialogDescription')}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-5 py-2">
              {/* Step 1: Snapshot */}
              <div className="rounded-lg border bg-card p-3 space-y-2">
                <div className="flex items-start gap-2.5">
                  <Checkbox
                    id="offboard-snap"
                    checked={takeSnapshot}
                    onCheckedChange={(c) => setTakeSnapshot(c === true)}
                    className="mt-0.5"
                  />
                  <div className="space-y-0.5">
                    <Label htmlFor="offboard-snap" className="font-medium cursor-pointer flex items-center gap-1.5">
                      <Camera className="size-3.5 text-muted-foreground" />
                      {t('peopleUI.offboarding.stepSnapshot')}
                    </Label>
                    <p className="text-caption text-muted-foreground">
                      {t('peopleUI.offboarding.stepSnapshotDesc')}
                    </p>
                  </div>
                </div>
                {takeSnapshot && (
                  <Input
                    value={snapshotDesc}
                    onChange={(e) => setSnapshotDesc(e.target.value)}
                    className="h-8 text-small ml-6 w-[calc(100%-1.5rem)]"
                    placeholder={t('peopleUI.text.snapshotDescription')}
                  />
                )}
              </div>

              {/* Step 2: Lock Account */}
              <div className="rounded-lg border bg-card p-3">
                <div className="flex items-start gap-2.5">
                  <Checkbox
                    id="offboard-lock"
                    checked={lockAccount}
                    onCheckedChange={(c) => setLockAccount(c === true)}
                    className="mt-0.5"
                  />
                  <div className="space-y-0.5">
                    <Label htmlFor="offboard-lock" className="font-medium cursor-pointer flex items-center gap-1.5">
                      <Lock className="size-3.5 text-muted-foreground" />
                      {t('peopleUI.offboarding.stepLock')}
                    </Label>
                    <p className="text-caption text-muted-foreground">
                      {t('peopleUI.offboarding.stepLockDesc')}
                    </p>
                  </div>
                </div>
              </div>

              {/* Step 3: Remove Group Memberships */}
              <div className="rounded-lg border bg-card p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <Users className="size-3.5 text-muted-foreground" />
                    <span className="text-small font-medium text-foreground">
                      {t('peopleUI.offboarding.stepGroups')}
                    </span>
                  </div>
                  {groups.length > 0 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-6 text-caption text-primary"
                      onClick={() =>
                        setSelectedGroups(
                          selectedGroups.length === groups.length ? [] : groups.map((g) => g.dn),
                        )
                      }
                    >
                      {selectedGroups.length === groups.length ? t('peopleUI.text.deselectAll') : t('peopleUI.text.selectAll')}
                    </Button>
                  )}
                </div>
                <p className="text-caption text-muted-foreground">
                  {t('peopleUI.offboarding.stepGroupsDesc')}
                </p>

                {groups.length === 0 ? (
                  <p className="text-caption text-muted-foreground italic pt-1">
                    {t('peopleUI.offboarding.noGroups')}
                  </p>
                ) : (
                  <div className="max-h-36 overflow-y-auto space-y-1.5 pt-1">
                    {groups.map((g) => (
                      <div
                        key={g.dn}
                        className="flex items-center gap-2 rounded-md p-1.5 hover:bg-muted/40 cursor-pointer text-small"
                        onClick={() => handleToggleGroup(g.dn)}
                      >
                        <Checkbox
                          checked={selectedGroups.includes(g.dn)}
                          onCheckedChange={() => handleToggleGroup(g.dn)}
                        />
                        <span className="font-medium">{g.name}</span>
                        <span className="text-caption text-muted-foreground truncate">{g.dn}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Step 4: Move department (optional) */}
              <div className="rounded-lg border bg-card p-3 space-y-2">
                <div className="flex items-start gap-2.5">
                  <Checkbox
                    id="offboard-move"
                    checked={moveAccount}
                    onCheckedChange={(c) => setMoveAccount(c === true)}
                    className="mt-0.5"
                  />
                  <div className="space-y-0.5 flex-1">
                    <Label htmlFor="offboard-move" className="font-medium cursor-pointer flex items-center gap-1.5">
                      <FolderInput className="size-3.5 text-muted-foreground" />
                      {t('peopleUI.offboarding.stepMove')}
                    </Label>
                    <p className="text-caption text-muted-foreground">
                      {moveAccount
                        ? t('peopleUI.offboarding.stepMoveDesc')
                        : t('peopleUI.offboarding.keepInPlace', { dept: userCurrentDept || topLevel })}
                    </p>
                  </div>
                </div>

                {moveAccount && (
                  <div className="pt-2 ml-6">
                    <Select value={targetDept} onValueChange={setTargetDept}>
                      <SelectTrigger className="w-full h-8 text-small">
                        <SelectValue placeholder={t('peopleUI.offboarding.targetDepartment')} />
                      </SelectTrigger>
                      <SelectContent>
                        {deptList.map((d) => (
                          <SelectItem key={d.dn} value={d.dn}>
                            <div className="flex items-center gap-1.5">
                              <Archive className="size-3.5 text-muted-foreground" />
                              <span>{d.label}</span>
                              <span className="text-caption text-muted-foreground">({d.dn})</span>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </div>
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
                variant="destructive"
                disabled={submitting}
                onClick={() => void handleExecute()}
              >
                {submitting && <Loader2 className="animate-spin" aria-hidden />}
                {t('peopleUI.offboarding.startAction')}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

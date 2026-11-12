import { Link, useNavigate } from '@tanstack/react-router'
import {
  Building2,
  Check,
  ChevronRight,
  Copy,
  History,
  Loader2,
  MoreHorizontal,
  Search,
  Trash2,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  useDeleteObjects,
  useObject,
  useObjectList,
  usePatchObject,
  useTypeDescriptor,
} from '@/api/hooks'
import type { ObjectListItem } from '@/api/types'
import { ErrorState } from '@/components/ErrorState'
import {
  ConfirmDialog,
  EntityHeader,
  FactList,
  OrgPath,
  SectionCard,
} from '@/components/patterns'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FieldRow } from '@/features/editor/FieldRow'
import { useObjectLdif } from '@/features/editor/api'
import { LdifDialog } from '@/features/editor/LdifDialog'
import { SaveReviewDialog } from '@/features/editor/SaveReviewDialog'
import { useUndoableSave } from '@/features/editor/undo'
import { SnapshotsPanel } from '@/features/editor/SnapshotsPanel'
import {
  computeChanges,
  listFieldDiffs,
  valuesFromDetail,
  type FieldDiff,
  type FormValues,
} from '@/lib/objects'
import { useTechnicalDetails } from '@/lib/preferences'
import { initials } from '@/lib/utils'
import { makeResolver } from '@/lib/validation'

interface GroupProfilePageProps {
  dn: string
}

export function GroupProfilePage({ dn }: GroupProfilePageProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const technical = useTechnicalDetails()

  const desc = useTypeDescriptor('group')
  const obj = useObject('group', dn)
  const patch = usePatchObject('group', dn)
  const del = useDeleteObjects('group')

  // Load users to resolve member names/details
  const usersQuery = useObjectList('user', { scope: 'sub', limit: 200 })
  const allUsers = useMemo<ObjectListItem[]>(() => usersQuery.data?.pages.flatMap((p) => p.items) ?? [], [usersQuery.data])
  const userMap = useMemo(() => {
    const map = new Map<string, ObjectListItem>()
    allUsers.forEach((u) => map.set(u.dn.toLowerCase(), u))
    return map
  }, [allUsers])

  const [activeTab, setActiveTab] = useState<'members' | 'properties' | 'advanced'>('members')
  const [memberSearch, setMemberSearch] = useState('')
  const [addMembersOpen, setAddMembersOpen] = useState(false)
  const [memberToRemove, setMemberToRemove] = useState<{ dn: string; name: string } | null>(null)
  const [deleteGroupOpen, setDeleteGroupOpen] = useState(false)
  const [ldifOpen, setLdifOpen] = useState(false)
  const [reviewDiffs, setReviewDiffs] = useState<FieldDiff[] | null>(null)
  const { takeUndoPoint, toastSaved } = useUndoableSave('group')
  const ldifQuery = useObjectLdif('group', dn, ldifOpen)
  const [copiedDn, setCopiedDn] = useState(false)

  // Add members dialog state
  const [searchUserQuery, setSearchUserQuery] = useState('')
  const [selectedUserDns, setSelectedUserDns] = useState<string[]>([])
  const [submittingAdd, setSubmittingAdd] = useState(false)

  // Inline editing for properties
  const [editingProps, setEditingProps] = useState(false)
  const [savingProps, setSavingProps] = useState(false)

  const detail = obj.data ?? null
  const descriptor = desc.data

  const initialValues = useMemo(() => {
    if (!descriptor || !detail) return { main: {} }
    return valuesFromDetail(descriptor, detail)
  }, [descriptor, detail])

  const resolver = useMemo(() => {
    if (!descriptor) return undefined
    return makeResolver(descriptor, () => ({ main: true }))
  }, [descriptor])

  const form = useForm<FormValues>({
    defaultValues: initialValues,
    resolver,
  })
  const { control, reset, getValues } = form

  const mainValues = (detail?.tabs.main?.values ?? {}) as Record<string, unknown>
  const groupName = String(mainValues.cn ?? dn)
  const groupDesc = mainValues.description ? String(mainValues.description) : null

  // Extract raw members array
  const rawMembers = mainValues.member
  const memberDns: string[] = useMemo(() => {
    if (Array.isArray(rawMembers)) return rawMembers as string[]
    if (typeof rawMembers === 'string' && rawMembers) return [rawMembers]
    return []
  }, [rawMembers])

  // Filter members by search
  const filteredMembers = useMemo(() => {
    if (!memberSearch.trim()) return memberDns
    const lower = memberSearch.toLowerCase()
    return memberDns.filter((mDn) => {
      const u = userMap.get(mDn.toLowerCase())
      const name = String(u?.values.cn ?? u?.values.uid ?? mDn)
      const uid = String(u?.values.uid ?? '')
      return name.toLowerCase().includes(lower) || uid.toLowerCase().includes(lower) || mDn.toLowerCase().includes(lower)
    })
  }, [memberDns, memberSearch, userMap])

  // Users available to add (not already members)
  const currentMemberSet = useMemo(() => {
    const set: Record<string, true> = {}
    memberDns.forEach((m) => {
      set[m.toLowerCase()] = true
    })
    return set
  }, [memberDns])

  const availableToAdd = useMemo(() => {
    const lower = searchUserQuery.toLowerCase().trim()
    return allUsers.filter((u) => {
      if (currentMemberSet[u.dn.toLowerCase()]) return false
      if (!lower) return true
      const name = String(u.values.cn ?? u.values.uid ?? u.dn)
      const uid = String(u.values.uid ?? '')
      return name.toLowerCase().includes(lower) || uid.toLowerCase().includes(lower)
    })
  }, [allUsers, currentMemberSet, searchUserQuery])

  const copyDn = () => {
    void navigator.clipboard?.writeText(dn).then(() => {
      setCopiedDn(true)
      setTimeout(() => setCopiedDn(false), 2000)
    })
  }

  // Remove member action
  const handleRemoveMember = async (memberDn: string) => {
    try {
      const remaining = memberDns.filter((m) => m.toLowerCase() !== memberDn.toLowerCase())
      await patch.mutateAsync({
        tabs: {
          main: {
            active: true,
            values: { member: remaining },
          },
        },
      })
      toast.success(t('peopleUI.groupProfile.members.memberRemoved'))
      setMemberToRemove(null)
      void obj.refetch()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('peopleUI.errors.removeMember'))
    }
  }

  // Add members action
  const handleAddMembers = async () => {
    if (selectedUserDns.length === 0) return
    setSubmittingAdd(true)
    try {
      const updated = [...memberDns, ...selectedUserDns]
      await patch.mutateAsync({
        tabs: {
          main: {
            active: true,
            values: { member: updated },
          },
        },
      })
      toast.success(
        t('peopleUI.groupProfile.addDialog.success', {
          count: selectedUserDns.length,
        }),
      )
      setAddMembersOpen(false)
      setSelectedUserDns([])
      setSearchUserQuery('')
      void obj.refetch()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('peopleUI.errors.addMembers'))
    } finally {
      setSubmittingAdd(false)
    }
  }

  // Save properties action
  const handleSaveProperties = async (confirmed = false) => {
    if (!descriptor || !detail) return
    if (!confirmed) {
      const diffs = listFieldDiffs(
        descriptor,
        valuesFromDetail(descriptor, detail),
        getValues(),
        { main: true },
      )
      if (diffs.length > 0) {
        setReviewDiffs(diffs)
        return
      }
    }
    setSavingProps(true)
    try {
      const currentValues = getValues()
      const baselineValues = valuesFromDetail(descriptor, detail)
      const changes = computeChanges(
        descriptor,
        baselineValues,
        { main: true },
        currentValues,
        { main: true },
      )

      if (Object.keys(changes).length === 0) {
        setEditingProps(false)
        return
      }

      const undoId = await takeUndoPoint(detail.dn)
      await patch.mutateAsync({ tabs: changes })
      toastSaved(t('common.saved'), undoId, () => void obj.refetch())
      setEditingProps(false)
      void obj.refetch()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('peopleUI.errors.save'))
    } finally {
      setSavingProps(false)
    }
  }

  // Delete group action
  const handleDeleteGroup = async () => {
    try {
      await del.mutateAsync([dn])
      toast.success(t('listing.deleted', { count: 1 }))
      void navigate({ to: '/types/$type', params: { type: 'group' } })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('peopleUI.errors.delete'))
    }
  }

  if (desc.isError) return <ErrorState error={desc.error} onRetry={() => void desc.refetch()} />
  if (obj.isError) return <ErrorState error={obj.error} onRetry={() => void obj.refetch()} />

  if (!descriptor || !detail) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label={t('common.loading')}>
        <div className="flex items-center gap-4">
          <Skeleton className="size-14 rounded-xl" />
          <div className="space-y-2">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-4 w-72" />
          </div>
        </div>
        <Skeleton className="h-96 w-full rounded-md" />
      </div>
    )
  }

  const propsSection = descriptor.tabs[0]?.sections.find((s) => s.name === 'general' || s.name === 'properties')

  return (
    <div className="space-y-6 pb-24">
      {/* 1. Entity Header */}
      <EntityHeader
        name={groupName}
        subtitle={groupDesc ?? undefined}
        icon={<Users className="size-6 text-primary" />}
        meta={[
          {
            icon: <Building2 className="size-3.5" />,
            content: <OrgPath dn={detail.dn} />,
          },
        ]}
        breadcrumbs={
          <nav aria-label="Breadcrumbs" className="flex items-center gap-1.5 text-caption text-muted-foreground">
            <Link to="/types/$type" params={{ type: 'group' }} className="hover:text-foreground">
              Groups
            </Link>
            <ChevronRight className="size-3.5" aria-hidden />
            <span className="text-foreground font-medium truncate">{groupName}</span>
          </nav>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="default"
              size="sm"
              onClick={() => setAddMembersOpen(true)}
            >
              <UserPlus className="size-4" />
              {t('peopleUI.groupProfile.members.addMembers')}
            </Button>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon-sm" aria-label="More actions">
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuItem onClick={() => setActiveTab('advanced')}>
                  <History className="size-4" />
                  Saved versions
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => setDeleteGroupOpen(true)}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2 className="size-4" />
                  Delete group
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        }
      />

      {/* Technical details mono bar */}
      {technical && (
        <div className="flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-small shadow-xs">
          <span className="text-caption font-semibold tracking-wider uppercase text-muted-foreground shrink-0">
            {t('peopleUI.userProfile.technicalDn')}:
          </span>
          <span className="font-mono text-small text-muted-foreground truncate">{dn}</span>
          <button
            type="button"
            onClick={copyDn}
            className="text-muted-foreground hover:text-foreground shrink-0 p-0.5"
            aria-label={t('patterns.copyDn')}
          >
            {copiedDn ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
          </button>
        </div>
      )}

      {/* 2. Tabs */}
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
        <TabsList className="mb-6">
          <TabsTrigger value="members">{t('peopleUI.groupProfile.tabs.members')}</TabsTrigger>
          <TabsTrigger value="properties">{t('peopleUI.groupProfile.tabs.properties')}</TabsTrigger>
          <TabsTrigger value="advanced">{t('peopleUI.groupProfile.tabs.advanced')}</TabsTrigger>
        </TabsList>

        {/* Tab 1: Members */}
        <TabsContent value="members" className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="relative w-full sm:w-72">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
              <Input
                value={memberSearch}
                onChange={(e) => setMemberSearch(e.target.value)}
                placeholder={t('peopleUI.groupProfile.members.searchPlaceholder')}
                className="h-8 pl-8 text-small pr-8"
              />
              {memberSearch && (
                <button
                  type="button"
                  onClick={() => setMemberSearch('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </div>

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setAddMembersOpen(true)}
            >
              <UserPlus className="size-3.5" />
              {t('peopleUI.groupProfile.members.addMembers')}
            </Button>
          </div>

          {memberDns.length === 0 ? (
            <div className="rounded-lg border bg-card p-8 text-center text-muted-foreground">
              <Users className="size-8 mx-auto mb-2 opacity-40" />
              <p className="font-medium text-foreground">{t('peopleUI.groupProfile.members.empty')}</p>
            </div>
          ) : filteredMembers.length === 0 ? (
            <div className="rounded-lg border bg-card p-6 text-center text-muted-foreground">
              <p className="text-small">{t('peopleUI.groupProfile.members.noSearchResults')}</p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-lg border bg-card">
              <table className="w-full text-body">
                <thead className="border-b bg-muted/40 text-left text-small text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">{t('peopleUI.text.person')}</th>
                    <th className="hidden px-4 py-2.5 font-medium sm:table-cell">{t('peopleUI.text.login')}</th>
                    <th className="hidden px-4 py-2.5 font-medium md:table-cell">{t('peopleUI.text.department')}</th>
                    <th className="w-16 px-4 py-2.5 text-right font-medium"><span className="sr-only">{t('peopleUI.text.actions')}</span></th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filteredMembers.map((mDn) => {
                    const user = userMap.get(mDn.toLowerCase())
                    const name = String(user?.values.cn ?? user?.values.uid ?? mDn)
                    const uid = String(user?.values.uid ?? '')
                    const deptDn = user ? String(user.values.base ?? user.dn) : mDn

                    return (
                      <tr key={mDn} className="hover:bg-muted/30 transition-colors">
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-3">
                            <Avatar className="size-8">
                              <AvatarFallback className="bg-primary-soft text-caption font-semibold text-primary">
                                {initials(name)}
                              </AvatarFallback>
                            </Avatar>
                            <div className="min-w-0">
                              <Link
                                to="/types/$type/$dn"
                                params={{ type: 'user', dn: mDn }}
                                className="truncate font-medium text-foreground hover:text-signal block"
                              >
                                {name}
                              </Link>
                              <span className="text-caption text-muted-foreground sm:hidden block font-mono">
                                {uid}
                              </span>
                            </div>
                          </div>
                        </td>
                        <td className="hidden px-4 py-2.5 sm:table-cell font-mono text-small text-muted-foreground">
                          {uid || '—'}
                        </td>
                        <td className="hidden px-4 py-2.5 md:table-cell">
                          <OrgPath dn={deptDn} />
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-xs"
                            className="text-muted-foreground hover:text-destructive"
                            onClick={() => setMemberToRemove({ dn: mDn, name })}
                            title={t('peopleUI.groupProfile.members.removeMember')}
                          >
                            <Trash2 className="size-3.5" />
                          </Button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>

        {/* Tab 2: Properties */}
        <TabsContent value="properties" className="space-y-6">
          <SectionCard
            title={propsSection?.label ?? 'Properties'}
            editable
            editing={editingProps}
            saving={savingProps}
            onEdit={() => setEditingProps(true)}
            onSave={() => void handleSaveProperties()}
            onCancel={() => {
              setEditingProps(false)
              reset(initialValues)
            }}
          >
            {editingProps ? (
              <div className="grid gap-4 sm:grid-cols-2">
                {propsSection?.attributes.map((attr) => (
                  <FieldRow
                    key={attr.name}
                    control={control}
                    tab="main"
                    attr={attr}
                    readOnly={false}
                  />
                ))}
              </div>
            ) : (
              <FactList
                columns={2}
                items={[
                  { label: t('peopleUI.text.name'), value: groupName },
                  { label: t('peopleUI.text.description'), value: groupDesc ?? null },
                  { label: t('peopleUI.text.department'), value: <OrgPath dn={detail.dn} /> },
                  { label: t('peopleUI.text.memberCount'), value: t('peopleUI.text.members', { count: memberDns.length }) },
                ]}
              />
            )}
          </SectionCard>
        </TabsContent>

        {/* Tab 3: Advanced */}
        <TabsContent value="advanced" className="space-y-6">
          <SectionCard title={t('peopleUI.userProfile.advanced.history')}>
            <SnapshotsPanel type="group" dn={dn} onRestored={() => void obj.refetch()} />
          </SectionCard>

          <SectionCard
            title={t('peopleUI.userProfile.advanced.ldif')}
            description={t('peopleUI.userProfile.advanced.ldifDescription')}
            actions={
              <Button variant="outline" size="sm" onClick={() => setLdifOpen(true)}>
                View LDIF
              </Button>
            }
          >
            <p className="text-small text-muted-foreground font-mono truncate">{dn}</p>
          </SectionCard>
        </TabsContent>
      </Tabs>

      {/* Add Members Dialog */}
      <Dialog open={addMembersOpen} onOpenChange={setAddMembersOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <UserPlus className="size-5 text-primary" aria-hidden />
              <span>{t('peopleUI.groupProfile.addDialog.title', { group: groupName })}</span>
            </DialogTitle>
            <DialogDescription>
              {t('peopleUI.groupProfile.addDialog.description')}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
              <Input
                value={searchUserQuery}
                onChange={(e) => setSearchUserQuery(e.target.value)}
                placeholder={t('peopleUI.groupProfile.addDialog.searchPlaceholder')}
                className="h-8 pl-8 text-small"
              />
            </div>

            <div className="max-h-64 overflow-y-auto space-y-1 rounded-lg border bg-card p-2">
              {availableToAdd.length === 0 ? (
                <p className="p-4 text-center text-small text-muted-foreground italic">
                  {t('peopleUI.groupProfile.addDialog.noResults', { query: searchUserQuery })}
                </p>
              ) : (
                availableToAdd.map((u) => {
                  const uName = String(u.values.cn ?? u.values.uid ?? u.dn)
                  const uid = String(u.values.uid ?? '')
                  const isChecked = selectedUserDns.includes(u.dn)

                  return (
                    <div
                      key={u.dn}
                      className="flex items-center justify-between rounded-md p-2 hover:bg-muted/40 cursor-pointer text-small"
                      onClick={() =>
                        setSelectedUserDns((prev) =>
                          isChecked ? prev.filter((x) => x !== u.dn) : [...prev, u.dn],
                        )
                      }
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Checkbox
                          checked={isChecked}
                          onCheckedChange={() =>
                            setSelectedUserDns((prev) =>
                              isChecked ? prev.filter((x) => x !== u.dn) : [...prev, u.dn],
                            )
                          }
                        />
                        <Avatar className="size-7">
                          <AvatarFallback className="bg-primary-soft text-micro font-semibold text-primary">
                            {initials(uName)}
                          </AvatarFallback>
                        </Avatar>
                        <div className="min-w-0">
                          <span className="font-medium text-foreground block truncate">{uName}</span>
                          <span className="text-caption text-muted-foreground block font-mono">
                            {uid}
                          </span>
                        </div>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
            {selectedUserDns.length > 0 && (
              <span className="text-caption text-primary font-medium">
                {t('peopleUI.groupProfile.addDialog.selectedCount', { count: selectedUserDns.length })}
              </span>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={submittingAdd}
              onClick={() => setAddMembersOpen(false)}
            >
              {t('common.cancel')}
            </Button>
            <Button
              type="button"
              disabled={selectedUserDns.length === 0 || submittingAdd}
              onClick={() => void handleAddMembers()}
            >
              {submittingAdd && <Loader2 className="animate-spin" aria-hidden />}
              {t('peopleUI.groupProfile.addDialog.submit')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Remove Member Confirmation Dialog */}
      <ConfirmDialog
        open={Boolean(memberToRemove)}
        onOpenChange={(o) => (!o ? setMemberToRemove(null) : undefined)}
        title={t('peopleUI.groupProfile.members.removeMemberTitle')}
        description={
          memberToRemove
            ? t('peopleUI.groupProfile.members.removeConfirm', {
                name: memberToRemove.name,
                group: groupName,
              })
            : undefined
        }
        confirmLabel={t('peopleUI.groupProfile.members.removeMember')}
        destructive
        onConfirm={() => {
          if (memberToRemove) void handleRemoveMember(memberToRemove.dn)
        }}
      />

      {/* Delete Group Confirmation Dialog */}
      <ConfirmDialog
        open={deleteGroupOpen}
        onOpenChange={setDeleteGroupOpen}
        title={t('peopleUI.groupProfile.deleteDialog.title', { name: groupName })}
        description={t('peopleUI.groupProfile.deleteDialog.description')}
        confirmLabel={t('peopleUI.groupProfile.deleteDialog.confirmLabel')}
        destructive
        confirmText={groupName}
        onConfirm={() => void handleDeleteGroup()}
      />

      <SaveReviewDialog
        open={reviewDiffs !== null}
        target={detail?.dn ?? dn}
        diffs={reviewDiffs ?? []}
        busy={savingProps}
        onCancel={() => setReviewDiffs(null)}
        onConfirm={() => {
          setReviewDiffs(null)
          void handleSaveProperties(true)
        }}
      />

      <LdifDialog
        open={ldifOpen}
        onOpenChange={setLdifOpen}
        ldif={ldifQuery.data ?? `dn: ${dn}\n`}
        title={groupName}
        dn={dn}
        loading={ldifQuery.isPending && ldifOpen}
      />
    </div>
  )
}

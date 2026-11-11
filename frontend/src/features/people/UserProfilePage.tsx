import { Link, useNavigate } from '@tanstack/react-router'
import {
  Building2,
  Check,
  ChevronRight,
  Copy,
  ExternalLink,
  FolderInput,
  History,
  KeyRound,
  Lock,
  LockOpen,
  Mail,
  MoreHorizontal,
  Phone,
  Plus,
  Shield,
  ShieldAlert,
  Trash2,
  UserMinus,
  Users,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import {
  useAccountLock,
  useDeleteObjects,
  useObject,
  useObjectAccountLocked,
  usePatchObject,
  useTypeDescriptor,
  useTypes,
} from '@/api/hooks'
import type { AttributeDescriptor, LockInfo, ObjectDetail } from '@/api/types'
import { ErrorState } from '@/components/ErrorState'
import {
  ConfirmDialog,
  EntityHeader,
  FactList,
  OrgPath,
  SectionCard,
  StatusBadge,
} from '@/components/patterns'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useObjectLdif, useReferences, useSecondFactors, useSnapshots } from '@/features/editor/api'
import { FieldRow } from '@/features/editor/FieldRow'
import { LdifDialog } from '@/features/editor/LdifDialog'
import { LockedDialog } from '@/features/editor/LockedDialog'
import { ReferencesPanel } from '@/features/editor/ReferencesPanel'
import { SecondFactorsPanel } from '@/features/editor/SecondFactorsPanel'
import { UserActivity } from '@/features/audit/ObjectHistory'
import { SnapshotsPanel } from '@/features/editor/SnapshotsPanel'
import { showTriggerOutput } from '@/features/editor/triggerOutput'
import { CopyMoveDialog } from '@/features/listing/CopyMoveDialog'
import {
  computeChanges,
  objectToLdif,
  rdnValue,
  valuesFromDetail,
  type FormValues,
} from '@/lib/objects'
import { useTechnicalDetails } from '@/lib/preferences'
import { makeResolver } from '@/lib/validation'
import { AddToGroupDialog } from './AddToGroupDialog'
import { OffboardingDialog } from './OffboardingDialog'
import { ResetPasswordDialog } from './ResetPasswordDialog'
import { getUserStatus } from './utils'

interface UserProfilePageProps {
  dn: string
}

export function UserProfilePage({ dn }: UserProfilePageProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const technical = useTechnicalDetails()

  const types = useTypes()
  const desc = useTypeDescriptor('user')
  const obj = useObject('user', dn)
  const patch = usePatchObject('user', dn)
  const del = useDeleteObjects('user')
  const accountLock = useAccountLock('user')
  const isLockedQuery = useObjectAccountLocked('user', dn)
  const referencesQuery = useReferences('user', dn)
  const secondFactorsQuery = useSecondFactors(dn)
  const secondFactorMethods: string[] = []
  if (secondFactorsQuery.data?.totp)
    secondFactorMethods.push(t('peopleUI.userProfile.securitySummary.authenticatorApp'))
  if (secondFactorsQuery.data && secondFactorsQuery.data.security_keys.length > 0)
    secondFactorMethods.push(
      t('peopleUI.userProfile.securitySummary.securityKeys', {
        count: secondFactorsQuery.data.security_keys.length,
      }),
    )
  const snapshotsQuery = useSnapshots('user', dn)
  const canCopy = types.data?.find((x) => x.name === 'user')?.can_create ?? false
  // Modals state
  const [activeTab, setActiveTab] = useState<'overview' | 'details' | 'access' | 'security' | 'advanced'>('overview')
  const [resetPwOpen, setResetPwOpen] = useState(false)
  const [addToGroupOpen, setAddToGroupOpen] = useState(false)
  const [offboardOpen, setOffboardOpen] = useState(false)
  const [moveOpen, setMoveOpen] = useState(false)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [ldifOpen, setLdifOpen] = useState(false)
  const [copiedDn, setCopiedDn] = useState(false)
  // Detail data
  const detail: ObjectDetail | null = obj.data ?? null
  const descriptor = desc.data

  const ldifQuery = useObjectLdif('user', dn, ldifOpen)
  const localLdif = useMemo(() => {
    if (!descriptor || !detail) return ''
    return objectToLdif(descriptor, dn, valuesFromDetail(descriptor, detail), { main: true })
  }, [descriptor, detail, dn])
  const ldifText = ldifQuery.data ?? localLdif

  // Inline editing state for Details tab sections
  const [editingSection, setEditingSection] = useState<string | null>(null)
  const [savingSection, setSavingSection] = useState<string | null>(null)
  const [lockInfo, setLockInfo] = useState<LockInfo | null>(null)
  const isAcquiredLock = useRef(false)

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
    mode: 'onTouched',
  })
  const { control, reset, getValues } = form

  // Reset form when detail updates
  useEffect(() => {
    if (detail && descriptor) {
      reset(valuesFromDetail(descriptor, detail))
    }
  }, [detail, descriptor, reset])

  // Release lock on unmount if held
  useEffect(() => {
    return () => {
      if (isAcquiredLock.current && detail) {
        void api.unlockObject('user', detail.dn).catch(() => undefined)
      }
    }
  }, [detail])

  // Derived user facts
  const mainValues = (detail?.tabs.main?.values ?? {}) as Record<string, unknown>
  const cnVal = String(mainValues.cn ?? mainValues.uid ?? dn)
  const uidVal = String(mainValues.uid ?? '')
  const mailVal = mainValues.mail ? String(mainValues.mail) : null
  const phoneVal = Array.isArray(mainValues.telephoneNumber)
    ? String(mainValues.telephoneNumber[0] ?? '')
    : mainValues.telephoneNumber
      ? String(mainValues.telephoneNumber)
      : null
  const employeeTypeVal = mainValues.employeeType ? String(mainValues.employeeType) : null
  const photoVal = typeof mainValues.jpegPhoto === 'string' && mainValues.jpegPhoto ? mainValues.jpegPhoto : null

  const isLocked = Boolean(isLockedQuery.data)
  const userStatus = getUserStatus({ locked: isLocked, values: mainValues })

  // Groups and roles from references
  const references = useMemo(() => referencesQuery.data ?? [], [referencesQuery.data])
  const userGroups = useMemo(() => {
    return references
      .filter((r) => r.type === 'group')
      .map((r) => ({ dn: r.dn, name: r.label || r.dn }))
  }, [references])

  const userRoles = useMemo(() => {
    return references
      .filter((r) => r.type === 'role')
      .map((r) => ({ dn: r.dn, name: r.label || r.dn }))
  }, [references])

  const copyDn = useCallback(() => {
    void navigator.clipboard?.writeText(dn).then(() => {
      setCopiedDn(true)
      setTimeout(() => setCopiedDn(false), 2000)
    })
  }, [dn])

  // Lock toggle handler
  const handleToggleLock = async () => {
    const doLock = !isLocked
    try {
      await accountLock.mutateAsync({ dns: [dn], lock: doLock })
      toast.success(
        t(doLock ? 'listing.lockedCount' : 'listing.unlockedCount', { count: 1 }),
      )
      void obj.refetch()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('peopleUI.errors.lockToggle'))
    }
  }

  // Delete user handler
  const handleDeleteUser = async () => {
    try {
      await del.mutateAsync([dn])
      toast.success(t('listing.deleted', { count: 1 }))
      void navigate({ to: '/types/$type', params: { type: 'user' } })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('peopleUI.errors.delete'))
    }
  }

  // Section inline editing handlers
  const handleStartEditSection = async (sectionName: string) => {
    if (!detail) return
    try {
      const lockRes = await api.lockObject('user', detail.dn)
      if (lockRes.lock) isAcquiredLock.current = true
      setEditingSection(sectionName)
    } catch (e) {
      if (isApiError(e) && e.code === 'locked' && e.lock) {
        setLockInfo(e.lock as LockInfo)
      } else {
        // Allow editing locally even if locking endpoint fails
        setEditingSection(sectionName)
      }
    }
  }

  const handleCancelSection = () => {
    if (isAcquiredLock.current && detail) {
      void api.unlockObject('user', detail.dn).catch(() => undefined)
      isAcquiredLock.current = false
    }
    setEditingSection(null)
    reset(initialValues)
  }

  const handleSaveSection = async (sectionName: string) => {
    if (!descriptor || !detail) return
    setSavingSection(sectionName)
    try {
      const currentValues = getValues()
      const mainSection = descriptor.tabs[0]?.sections.find((s) => s.name === sectionName)
      if (!mainSection) {
        setEditingSection(null)
        return
      }

      const baselineValues = valuesFromDetail(descriptor, detail)
      const changes = computeChanges(
        descriptor,
        baselineValues,
        { main: true },
        currentValues,
        { main: true },
      )

      if (Object.keys(changes).length === 0) {
        handleCancelSection()
        return
      }

      const res = await patch.mutateAsync({ tabs: changes })
      showTriggerOutput(res)
      toast.success(t('common.saved'))
      if (isAcquiredLock.current) {
        void api.unlockObject('user', detail.dn).catch(() => undefined)
        isAcquiredLock.current = false
      }
      setEditingSection(null)
      void obj.refetch()
    } catch (err) {
      if (isApiError(err) && err.code === 'locked' && err.lock) {
        setLockInfo(err.lock as LockInfo)
      } else {
        toast.error(err instanceof Error ? err.message : t('peopleUI.errors.save'))
      }
    } finally {
      setSavingSection(null)
    }
  }

  // Remove member from group directly
  const handleRemoveFromGroup = async (groupDn: string, groupName: string) => {
    try {
      const groupObj = await api.getObject('group', groupDn)
      const currentMembersRaw = groupObj.tabs.main?.values.member
      const currentMembers: string[] = Array.isArray(currentMembersRaw)
        ? (currentMembersRaw as string[])
        : typeof currentMembersRaw === 'string' && currentMembersRaw
          ? [currentMembersRaw]
          : []

      const remaining = currentMembers.filter((m) => m.toLowerCase() !== dn.toLowerCase())
      await api.patchObject('group', groupDn, {
        tabs: {
          main: {
            active: true,
            values: { member: remaining },
          },
        },
      })
      toast.success(`Removed from ${groupName}`)
      void referencesQuery.refetch()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('peopleUI.errors.removeFromGroup'))
    }
  }

  // Helper for rendering fact values
  const renderFactValue = (attr: AttributeDescriptor, val: unknown) => {
    if (val === null || val === undefined || val === '') return '—'
    if (attr.kind === 'department') return <OrgPath dn={String(val)} includeSelf />
    if (attr.kind === 'image') return typeof val === 'string' ? <img src={val} alt="" className="size-10 rounded-md object-cover" /> : '—'
    if (typeof val === 'boolean') return val ? t('common.yes') : t('common.no')
    if (Array.isArray(val)) return val.join(', ')
    return String(val)
  }

  if (desc.isError) return <ErrorState error={desc.error} onRetry={() => void desc.refetch()} />
  if (obj.isError) return <ErrorState error={obj.error} onRetry={() => void obj.refetch()} />

  if (!descriptor || !detail) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label={t('common.loading')}>
        <div className="flex items-center gap-4">
          <Skeleton className="size-14 rounded-full" />
          <div className="space-y-2">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-4 w-72" />
          </div>
        </div>
        <Skeleton className="h-96 w-full rounded-md" />
      </div>
    )
  }

  const objectRights = detail.acl.main?.object ?? 'rwcdm'
  const canEdit = objectRights.includes('w') || objectRights.includes('m')
  const canDelete = objectRights.includes('d')

  // Overview Fact items
  const overviewFacts = [
    { label: t('peopleUI.userProfile.facts.login'), value: <span className="font-mono">{uidVal}</span> },
    { label: t('peopleUI.userProfile.facts.email'), value: mailVal ?? '—' },
    { label: t('peopleUI.userProfile.facts.department'), value: typeof mainValues.base === 'string' ? <OrgPath dn={mainValues.base} includeSelf /> : <OrgPath dn={detail.dn} /> },
    { label: t('peopleUI.userProfile.facts.employeeType'), value: employeeTypeVal ?? '—' },
    { label: t('peopleUI.userProfile.facts.language'), value: mainValues.preferredLanguage ? String(mainValues.preferredLanguage).toUpperCase() : '—' },
    { label: t('peopleUI.userProfile.facts.phone'), value: phoneVal ?? '—' },
    { label: t('peopleUI.userProfile.facts.manager'), value: mainValues.manager ? rdnValue(String(mainValues.manager)) : null },
    { label: t('peopleUI.userProfile.facts.internalId'), value: mainValues.internalId ? String(mainValues.internalId) : '—' },
  ]

  // Meta items for EntityHeader
  const headerMeta = [
    {
      icon: <Building2 />,
      content: typeof mainValues.base === 'string' ? <OrgPath dn={mainValues.base} includeSelf showIcon={false} /> : <OrgPath dn={detail.dn} showIcon={false} />,
    },
    ...(mailVal ? [{ icon: <Mail />, content: mailVal }] : []),
    ...(phoneVal ? [{ icon: <Phone />, content: phoneVal }] : []),
  ]

  return (
    <div className="space-y-6 pb-24">
      {/* 1. Entity Header */}
      <EntityHeader
        name={cnVal}
        subtitle={
          employeeTypeVal ? (
            <span className="capitalize">{employeeTypeVal}</span>
          ) : undefined
        }
        avatarUrl={photoVal}
        badges={<StatusBadge status={userStatus} />}
        meta={headerMeta}
        breadcrumbs={
          <nav aria-label="Breadcrumbs" className="flex items-center gap-1.5 text-caption text-muted-foreground">
            <Link to="/types/$type" params={{ type: 'user' }} className="hover:text-foreground">
              Users
            </Link>
            <ChevronRight className="size-3.5" aria-hidden />
            <span className="text-foreground font-medium truncate">{cnVal}</span>
          </nav>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setResetPwOpen(true)}
            >
              <KeyRound className="size-4" />
              {t('peopleUI.userProfile.actions.resetPassword')}
            </Button>

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void handleToggleLock()}
              disabled={accountLock.isPending}
            >
              {isLocked ? (
                <>
                  <LockOpen className="size-4" />
                  {t('peopleUI.userProfile.actions.unlock')}
                </>
              ) : (
                <>
                  <Lock className="size-4" />
                  {t('peopleUI.userProfile.actions.lock')}
                </>
              )}
            </Button>

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setAddToGroupOpen(true)}
            >
              <Users className="size-4" />
              {t('peopleUI.userProfile.actions.addToGroup')}
            </Button>

            <Button
              type="button"
              variant="outline"
              size="sm"
              className="border-warning/40 text-warning hover:bg-warning-soft hover:text-warning"
              onClick={() => setOffboardOpen(true)}
            >
              <UserMinus className="size-4" />
              {t('peopleUI.userProfile.actions.offboard')}
            </Button>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon-sm" aria-label={t('peopleUI.userProfile.actions.more')}>
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-52">
                {canCopy && (
                  <DropdownMenuItem
                    onClick={() =>
                      void navigate({
                        to: '/types/$type/new',
                        params: { type: 'user' },
                        search: { copy: dn },
                      })
                    }
                  >
                    <Copy className="size-4" />
                    {t('peopleUI.userProfile.actions.copyUser')}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => setMoveOpen(true)}>
                  <FolderInput className="size-4" />
                  {t('peopleUI.userProfile.actions.moveToDepartment')}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setActiveTab('advanced')}>
                  <History className="size-4" />
                  {t('peopleUI.userProfile.actions.snapshots')}
                </DropdownMenuItem>
                {canDelete && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={() => setDeleteConfirmOpen(true)}
                      className="text-destructive focus:text-destructive"
                    >
                      <Trash2 className="size-4" />
                      {t('peopleUI.userProfile.actions.deleteUser')}
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        }
      />

      {/* Technical details mono bar (when technical preference is ON) */}
      {technical && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1.5 rounded-lg border bg-card px-4 py-2.5 text-small shadow-xs">
          <div className="flex items-center gap-2">
            <span className="text-caption font-semibold tracking-wider uppercase text-muted-foreground">
              {t('peopleUI.userProfile.technicalLogin')}:
            </span>
            <span className="font-mono text-small font-medium text-foreground">{uidVal}</span>
          </div>
          <div className="flex min-w-0 items-center gap-2">
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
        </div>
      )}

      {/* 2. Tabs Navigation */}
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
        <TabsList className="mb-6">
          <TabsTrigger value="overview">{t('peopleUI.userProfile.tabs.overview')}</TabsTrigger>
          <TabsTrigger value="details">{t('peopleUI.userProfile.tabs.details')}</TabsTrigger>
          <TabsTrigger value="access">{t('peopleUI.userProfile.tabs.access')}</TabsTrigger>
          <TabsTrigger value="security">{t('peopleUI.userProfile.tabs.security')}</TabsTrigger>
          <TabsTrigger value="advanced">{t('peopleUI.userProfile.tabs.advanced')}</TabsTrigger>
        </TabsList>

        {/* Tab 1: Overview */}
        <TabsContent value="overview" className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Key Facts */}
            <SectionCard title={t('peopleUI.userProfile.facts.identityTitle')}>
              <FactList items={overviewFacts} columns={2} />
            </SectionCard>

            {/* Sign-in Security Overview */}
            <SectionCard
              title={t('peopleUI.userProfile.securitySummary.title')}
              actions={
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-caption text-primary"
                  onClick={() => setActiveTab('security')}
                >
                  {t('peopleUI.userProfile.securitySummary.manageSecurity')}
                  <ChevronRight className="size-3.5 ml-1" />
                </Button>
              }
            >
              <FactList
                columns={1}
                items={[
                  {
                    label: t('peopleUI.userProfile.securitySummary.twoFactor'),
                    value: secondFactorMethods.length > 0 ? (
                      <span className="flex items-center gap-1.5 text-foreground">
                        <Shield className="size-4 text-success" />
                        {secondFactorMethods.join(' · ')}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">
                        {t('peopleUI.userProfile.securitySummary.twoFactorNone')}
                      </span>
                    ),
                  },
                  {
                    label: t('peopleUI.userProfile.securitySummary.passwordStatus'),
                    value: mainValues.forcePasswordChange ? (
                      <span className="flex items-center gap-1.5 text-warning font-medium">
                        <ShieldAlert className="size-4" />
                        {t('peopleUI.userProfile.securitySummary.passwordMustChange')}
                      </span>
                    ) : (
                      <span className="text-foreground">
                        {t('peopleUI.userProfile.securitySummary.passwordNormal')}
                      </span>
                    ),
                  },
                ]}
              />
            </SectionCard>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* Groups Card */}
            <SectionCard
              title={t('peopleUI.userProfile.groups.title')}
              description={t('peopleUI.userProfile.groups.description')}
              actions={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setAddToGroupOpen(true)}
                >
                  <Plus className="size-3.5" />
                  {t('peopleUI.userProfile.groups.add')}
                </Button>
              }
            >
              {userGroups.length === 0 ? (
                <p className="text-small text-muted-foreground italic">
                  {t('peopleUI.userProfile.groups.empty')}
                </p>
              ) : (
                <div className="space-y-2">
                  {userGroups.map((g) => (
                    <div
                      key={g.dn}
                      className="flex items-center justify-between rounded-lg border bg-card p-3 shadow-xs hover:bg-muted/20 transition-colors"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Users className="size-4 text-primary shrink-0" aria-hidden />
                        <Link
                          to="/types/$type/$dn"
                          params={{ type: 'group', dn: g.dn }}
                          className="font-medium text-foreground hover:text-signal truncate"
                        >
                          {g.name}
                        </Link>
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        className="text-muted-foreground hover:text-destructive shrink-0"
                        onClick={() => void handleRemoveFromGroup(g.dn, g.name)}
                        title={t('peopleUI.userProfile.groups.remove')}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </SectionCard>

            {/* Roles Card */}
            <SectionCard
              title={t('peopleUI.userProfile.roles.title')}
              description={t('peopleUI.userProfile.roles.description')}
            >
              {userRoles.length === 0 ? (
                <p className="text-small text-muted-foreground italic">
                  {t('peopleUI.userProfile.roles.empty')}
                </p>
              ) : (
                <div className="space-y-2">
                  {userRoles.map((r) => (
                    <div
                      key={r.dn}
                      className="flex items-center justify-between rounded-lg border bg-card p-3 shadow-xs"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Shield className="size-4 text-primary shrink-0" aria-hidden />
                        <Link
                          to="/types/$type/$dn"
                          params={{ type: 'role', dn: r.dn }}
                          className="font-medium text-foreground hover:text-signal truncate"
                        >
                          {r.name}
                        </Link>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </SectionCard>
          </div>

          {/* Recent changes from snapshots */}
          <SectionCard
            title={t('peopleUI.userProfile.recentChanges.title')}
            actions={
              <Button
                variant="ghost"
                size="sm"
                className="text-caption text-primary"
                onClick={() => setActiveTab('advanced')}
              >
                {t('peopleUI.userProfile.recentChanges.viewAll')}
                <ChevronRight className="size-3.5 ml-1" />
              </Button>
            }
          >
            {snapshotsQuery.data && snapshotsQuery.data.length > 0 ? (
              <div className="space-y-2">
                {snapshotsQuery.data.slice(0, 3).map((snap) => (
                  <div
                    key={snap.id}
                    className="flex items-center justify-between rounded-md border bg-card px-3 py-2 text-small"
                  >
                    <div>
                      <p className="font-medium text-foreground">{snap.description || 'Snapshot'}</p>
                      <p className="text-caption text-muted-foreground">
                        {snap.created_at ? new Date(snap.created_at).toLocaleString() : '—'}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-small text-muted-foreground italic">
                {t('peopleUI.userProfile.recentChanges.empty')}
              </p>
            )}
          </SectionCard>
        </TabsContent>

        {/* Tab 2: Details (SectionCard per section with inline edit) */}
        <TabsContent value="details" className="space-y-6">
          {descriptor.tabs[0]?.sections.map((section) => {
            const isEditingThis = editingSection === section.name
            const isSavingThis = savingSection === section.name
            const formVals = getValues()

            return (
              <SectionCard
                key={section.name}
                title={section.label}
                editable={canEdit}
                editing={isEditingThis}
                saving={isSavingThis}
                onEdit={() => void handleStartEditSection(section.name)}
                onSave={() => void handleSaveSection(section.name)}
                onCancel={handleCancelSection}
              >
                {isEditingThis ? (
                  <div className="grid gap-4 sm:grid-cols-2">
                    {section.attributes.map((attr) => (
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
                    items={section.attributes
                      .filter((a) => a.kind !== 'hidden' && a.kind !== 'password')
                      .map((attr) => ({
                        label: attr.label,
                        value: renderFactValue(attr, formVals.main?.[attr.name]),
                      }))}
                  />
                )}
              </SectionCard>
            )
          })}
        </TabsContent>

        {/* Tab 3: Access */}
        <TabsContent value="access" className="space-y-6">
          <SectionCard
            title={t('peopleUI.userProfile.access.title')}
            description={t('peopleUI.userProfile.access.description')}
            actions={
              <Button asChild variant="outline" size="sm">
                <Link to="/admin/access">
                  <ExternalLink className="size-3.5" aria-hidden />
                  {t('peopleUI.userProfile.access.checkRights')}
                </Link>
              </Button>
            }
          >
            <FactList
              columns={2}
              items={[
                {
                  label: t('peopleUI.userProfile.access.roles'),
                  value: userRoles.length > 0 ? userRoles.map((r) => r.name).join(', ') : null,
                },
                {
                  label: t('peopleUI.userProfile.access.groups'),
                  value:
                    userGroups.length > 0
                      ? t('peopleUI.userProfile.access.groupCount', { count: userGroups.length })
                      : null,
                },
              ]}
            />
          </SectionCard>
        </TabsContent>

        {/* Tab 4: Security */}
        <TabsContent value="security" className="space-y-6">
          <SecondFactorsPanel dn={dn} />
          <UserActivity dn={dn} />
        </TabsContent>

        {/* Tab 5: Advanced */}
        <TabsContent value="advanced" className="space-y-6">
          {/* Every other tab of the type (plugins: Unix, mail, SSH keys...) opens in the full editor */}
          <SectionCard
            title={t('peopleUI.userProfile.advanced.tabsTitle')}
            description={t('peopleUI.userProfile.advanced.tabsDescription')}
            bodyClassName="p-0"
          >
            <ul className="divide-y">
              {descriptor.tabs.slice(1).map((tab) => {
                const active = detail.tabs[tab.name]?.active ?? false
                return (
                  <li key={tab.name} className="flex items-center gap-3 px-5 py-3">
                    <span className="min-w-0 flex-1">
                      <span className="block text-body font-medium text-foreground">{tab.label}</span>
                      {technical && (
                        <span className="block font-mono text-caption text-muted-foreground">{tab.name}</span>
                      )}
                    </span>
                    <Badge variant={active ? 'success' : 'neutral'}>
                      {active ? t('peopleUI.userProfile.advanced.active') : t('peopleUI.userProfile.advanced.inactive')}
                    </Badge>
                    <Button asChild variant="outline" size="sm">
                      <Link
                        to="/types/$type/$dn"
                        params={{ type: 'user', dn }}
                        search={{ view: 'generic', tab: tab.name }}
                      >
                        {active ? t('peopleUI.userProfile.advanced.open') : t('peopleUI.userProfile.advanced.enable')}
                      </Link>
                    </Button>
                  </li>
                )
              })}
            </ul>
          </SectionCard>

          {/* Directory References */}
          <SectionCard title={t('peopleUI.userProfile.advanced.references')}>
            <ReferencesPanel type="user" dn={dn} />
          </SectionCard>

          {/* Snapshots / Version History */}
          <SectionCard title={t('peopleUI.userProfile.advanced.history')}>
            <SnapshotsPanel type="user" dn={dn} onRestored={() => void obj.refetch()} />
          </SectionCard>

          {/* Raw LDIF */}
          <SectionCard
            title={t('peopleUI.userProfile.advanced.ldif')}
            description={t('peopleUI.userProfile.advanced.ldifDescription')}
            actions={
              <Button variant="outline" size="sm" onClick={() => setLdifOpen(true)}>
                {t('peopleUI.userProfile.advanced.viewLdif')}
              </Button>
            }
          >
            <p className="text-small text-muted-foreground font-mono truncate">{dn}</p>
          </SectionCard>
        </TabsContent>
      </Tabs>

      {/* Dialogs */}
      <ResetPasswordDialog
        open={resetPwOpen}
        onOpenChange={setResetPwOpen}
        userDn={dn}
        userName={cnVal}
        onSuccess={() => void obj.refetch()}
      />

      <AddToGroupDialog
        open={addToGroupOpen}
        onOpenChange={setAddToGroupOpen}
        userDns={[dn]}
        userName={cnVal}
        onSuccess={() => void referencesQuery.refetch()}
      />

      <OffboardingDialog
        open={offboardOpen}
        onOpenChange={setOffboardOpen}
        user={{
          dn,
          cn: cnVal,
          uid: uidVal,
          base: typeof mainValues.base === 'string' ? mainValues.base : undefined,
        }}
        groups={userGroups}
        onSuccess={() => {
          void obj.refetch()
          void isLockedQuery.refetch()
          void referencesQuery.refetch()
        }}
      />

      <ConfirmDialog
        open={deleteConfirmOpen}
        onOpenChange={setDeleteConfirmOpen}
        title={t('peopleUI.userProfile.deleteDialog.title', { name: cnVal })}
        description={t('peopleUI.userProfile.deleteDialog.description')}
        confirmLabel={t('peopleUI.userProfile.deleteDialog.confirmLabel')}
        destructive
        confirmText={uidVal}
        pending={del.isPending}
        onConfirm={() => void handleDeleteUser()}
      />

      <CopyMoveDialog
        open={moveOpen}
        onOpenChange={setMoveOpen}
        mode="move"
        type="user"
        descriptor={descriptor}
        items={[
          {
            dn: detail.dn,
            values: mainValues,
            locked: isLocked,
          },
        ]}
      />
      <LdifDialog
        open={ldifOpen}
        onOpenChange={setLdifOpen}
        ldif={ldifText}
        title={cnVal}
        loading={ldifQuery.isPending && ldifOpen}
      />
      <LockedDialog
        lock={lockInfo}
        onClose={() => setLockInfo(null)}
      />
    </div>
  )
}

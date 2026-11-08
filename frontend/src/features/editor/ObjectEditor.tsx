import { useBlocker, useNavigate } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import {
  useAccountLock,
  useCreateObject,
  useDeleteObjects,
  useObject,
  useObjectAccountLocked,
  usePatchObject,
  useTypeDescriptor,
} from '@/api/hooks'
import type { LockInfo, ObjectDetail, TypeDescriptor } from '@/api/types'
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
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ErrorState } from '@/components/ErrorState'
import {
  activeFromDetail,
  allAttributes,
  buildCreateTabs,
  computeChanges,
  defaultValue,
  deepEqual,
  listFieldDiffs,
  nameValue,
  objectToLdif,
  splitFieldKey,
  valuesFromDetail,
  type FormValues,
} from '@/lib/objects'
import { useScope } from '@/lib/scope'
import { makeResolver } from '@/lib/validation'
import { EditorHeader } from './EditorHeader'
import { EditorSaveBar } from './EditorSaveBar'
import { EditorSection } from './EditorSection'
import { EditorTabNav } from './EditorTabNav'
import { LdifDialog } from './LdifDialog'
import { LockedDialog } from './LockedDialog'
import { TemplatePicker } from './TemplatePicker'

const BASE_KEY = 'main.base'

interface Props {
  type: string
  /** null => create mode */
  dn: string | null
}

export function ObjectEditor({ type, dn }: Props) {
  const desc = useTypeDescriptor(type)
  const obj = useObject(type, dn)
  const { t } = useTranslation()

  if (desc.isError) return <ErrorState error={desc.error} onRetry={() => void desc.refetch()} />
  if (dn !== null && obj.isError) return <ErrorState error={obj.error} onRetry={() => void obj.refetch()} />
  if (!desc.data || (dn !== null && !obj.data)) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label={t('common.loading')}>
        <div className="flex items-center gap-4">
          <Skeleton className="size-10 rounded-md" />
          <div className="space-y-2">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-4 w-72" />
          </div>
        </div>
        <Skeleton className="h-96 w-full rounded-md" />
      </div>
    )
  }
  return <EditorInner key={dn ?? 'new'} desc={desc.data} detail={obj.data ?? null} />
}

function EditorInner({ desc, detail }: { desc: TypeDescriptor; detail: ObjectDetail | null }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const scope = useScope()
  const isCreate = detail === null
  const type = desc.name

  const initial = useMemo(() => {
    const v = valuesFromDetail(desc, detail)
    if (isCreate && v.main && !v.main.base) v.main.base = scope.base
    return v
  }, [desc, detail, isCreate, scope.base])

  const initialActive = useMemo(() => activeFromDetail(desc, detail), [desc, detail])

  const [active, setActive] = useState(initialActive)
  const activeRef = useRef(active)
  activeRef.current = active

  const [editing, setEditing] = useState(isCreate)
  const [tab, setTab] = useState(desc.tabs[0]?.name ?? 'main')
  const [lockInfo, setLockInfo] = useState<LockInfo | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [ldifOpen, setLdifOpen] = useState(false)
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null)

  const locked = useRef(false)
  const bypassGuard = useRef(false)
  const baseline = useRef({ values: initial, active: initialActive })

  const resolver = useMemo(() => makeResolver(desc, () => activeRef.current), [desc])
  const form = useForm<FormValues>({
    defaultValues: initial,
    resolver,
    mode: 'onTouched',
    reValidateMode: 'onChange',
  })
  const { control, formState } = form
  const current = form.watch() as FormValues

  const skip = useMemo(() => new Set([BASE_KEY]), [])
  const changes = useMemo(
    () => computeChanges(desc, baseline.current.values, baseline.current.active, current, active, skip),
    [desc, current, active, skip],
  )

  const diffs = useMemo(
    () => listFieldDiffs(desc, baseline.current.values, current, active),
    [desc, current, active],
  )

  const baseChanged =
    !isCreate &&
    !deepEqual(current.main?.base ?? null, baseline.current.values.main?.base ?? null) &&
    desc.tabs[0]?.sections.some((s) => s.attributes.some((a) => a.name === 'base' && a.kind === 'department'))

  const dirty = isCreate
    ? !deepEqual(current, baseline.current.values) || !deepEqual(active, baseline.current.active)
    : Object.keys(changes).length > 0 || !!baseChanged

  // Compute dirty tabs
  const dirtyTabs = useMemo(() => {
    const set = new Set<string>()
    for (const d of diffs) set.add(d.tab)
    return set
  }, [diffs])

  // Count errors by tab
  const errorsByTab = useMemo(() => {
    const counts: Record<string, number> = {}
    const errs = formState.errors as Record<string, Record<string, unknown>>
    for (const [tbName, tbErrors] of Object.entries(errs)) {
      if (tbErrors && typeof tbErrors === 'object') {
        counts[tbName] = Object.keys(tbErrors).length
      }
    }
    return counts
  }, [formState.errors])

  // Unsaved-changes blocker
  const blocker = useBlocker({
    shouldBlockFn: () => editing && dirty && !bypassGuard.current,
    withResolver: true,
    enableBeforeUnload: () => editing && dirty && !bypassGuard.current,
  })

  // Edit lock release on unmount
  useEffect(() => {
    return () => {
      if (locked.current && detail) void api.unlockObject(type, detail.dn).catch(() => undefined)
    }
  }, [type, detail])

  const patch = usePatchObject(type, detail?.dn ?? '')
  const create = useCreateObject(type)
  const del = useDeleteObjects(type)
  const accountLock = useAccountLock(type)
  const accountLockedQuery = useObjectAccountLocked(type, detail?.dn ?? null)

  const readOnlyMode = !editing
  const objectRights = detail?.acl[desc.tabs[0]?.name ?? 'main']?.object ?? 'rwcdm'
  const canEdit = isCreate || objectRights.includes('w') || objectRights.includes('m')
  const canDelete = !isCreate && objectRights.includes('d')

  const title = isCreate ? t('editor.newTitle', { type: desc.label }) : nameValue(desc, detail)

  // Find photo if available
  const photo = useMemo(() => {
    for (const tb of Object.values(current)) {
      if (tb && typeof tb.jpegPhoto === 'string' && tb.jpegPhoto) return tb.jpegPhoto
    }
    return null
  }, [current])

  const ldifText = useMemo(() => {
    return objectToLdif(desc, detail?.dn ?? 'new', current, active)
  }, [desc, detail, current, active])

  const applyServerErrors = (fields: Record<string, string>) => {
    let firstTab: string | null = null
    for (const [key, message] of Object.entries(fields)) {
      form.setError(key as never, { type: 'server', message })
      const parts = splitFieldKey(key)
      if (parts && !firstTab) firstTab = parts.tab
    }
    if (firstTab) setTab(firstTab)
  }

  const startEdit = async () => {
    if (!detail) return
    try {
      await api.lockObject(type, detail.dn)
      locked.current = true
      setEditing(true)
    } catch (e) {
      if (isApiError(e) && e.code === 'locked' && e.lock) setLockInfo(e.lock)
      else toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const release = async () => {
    if (locked.current && detail) {
      locked.current = false
      await api.unlockObject(type, detail.dn).catch(() => undefined)
    }
  }

  const resetTo = (d: ObjectDetail) => {
    const v = valuesFromDetail(desc, d)
    const a = activeFromDetail(desc, d)
    baseline.current = { values: v, active: a }
    setActive(a)
    form.reset(v)
  }

  const cancel = async () => {
    if (isCreate) {
      void navigate({ to: '/types/$type', params: { type } })
      return
    }
    await release()
    form.reset(baseline.current.values)
    setActive(baseline.current.active)
    setEditing(false)
  }

  const focusFirstError = (errors: Record<string, unknown>) => {
    const first = desc.tabs.find((tb) => errors[tb.name])
    if (first) setTab(first.name)
  }

  const save = form.handleSubmit(
    async (values) => {
      try {
        if (isCreate) {
          const base = (values.main?.base as string | null) ?? scope.base ?? ''
          const res = await create.mutateAsync({
            base,
            template: selectedTemplate,
            tabs: buildCreateTabs(desc, values, active),
          })
          toast.success(t('editor.created', { type: desc.label }))
          baseline.current = { values, active }
          bypassGuard.current = true
          form.reset(values)
          setTimeout(
            () => void navigate({ to: '/types/$type/$dn', params: { type, dn: res.dn } }),
            0,
          )
          return
        }
        if (!detail) return
        let result: ObjectDetail = detail
        if (Object.keys(changes).length > 0) {
          result = await patch.mutateAsync({ tabs: changes })
        }
        let finalDn = result.dn
        const newBase = values.main?.base
        if (baseChanged && typeof newBase === 'string') {
          const moved = await api.moveObject(type, detail.dn, newBase)
          finalDn = moved.dn
        }
        await release()
        toast.success(t('editor.saved'))
        if (finalDn !== detail.dn) {
          baseline.current = { values, active }
          bypassGuard.current = true
          form.reset(values)
          setEditing(false)
          void navigate({ to: '/types/$type/$dn', params: { type, dn: finalDn }, replace: true })
          return
        }
        resetTo(result)
        setEditing(false)
      } catch (e) {
        if (isApiError(e) && e.code === 'validation') {
          applyServerErrors(e.fields)
          toast.error(t('editor.validationFailed'))
        } else if (isApiError(e) && e.code === 'locked' && e.lock) {
          setLockInfo(e.lock)
        } else {
          toast.error(isApiError(e) ? e.message : t('common.error'))
        }
      }
    },
    (errors) => {
      focusFirstError(errors as Record<string, unknown>)
      toast.error(t('editor.fixErrors'))
    },
  )

  const doDelete = async () => {
    if (!detail) return
    const r = await del.mutateAsync([detail.dn])
    setConfirmDelete(false)
    if (r.failed) {
      toast.error(t('common.error'))
      return
    }
    await release()
    baseline.current = { values: current, active }
    form.reset(current)
    toast.success(t('editor.deleted'))
    setEditing(false)
    setTimeout(() => void navigate({ to: '/types/$type', params: { type } }), 0)
  }

  const toggleAccountLock = async () => {
    if (!detail) return
    const curLock = accountLockedQuery.data ?? false
    try {
      await accountLock.mutateAsync({ dns: [detail.dn], lock: !curLock })
      await accountLockedQuery.refetch()
      toast.success(t(curLock ? 'editor.accountUnlockedSuccess' : 'editor.accountLockedSuccess'))
    } catch {
      toast.error(t('common.error'))
    }
  }

  const currentTabObj = desc.tabs.find((tb) => tb.name === tab) ?? desc.tabs[0]
  const isCurrentTabActive = currentTabObj ? (active[currentTabObj.name] ?? false) : false
  const currentTabAcl = currentTabObj ? detail?.acl[currentTabObj.name] : undefined
  const canToggleCurrentTab =
    editing && currentTabObj && (isCreate || !currentTabAcl || currentTabAcl.object.includes('m'))

  return (
    <form onSubmit={(e) => void save(e)} noValidate className="flex flex-1 flex-col space-y-4">
      <EditorHeader
        desc={desc}
        dn={detail?.dn ?? null}
        title={title}
        photo={photo}
        isCreate={isCreate}
        editing={editing}
        dirty={dirty}
        canEdit={canEdit}
        canDelete={canDelete}
        isSubmitting={formState.isSubmitting}
        accountLocked={accountLockedQuery.data}
        onStartEdit={() => void startEdit()}
        onCancel={() => void cancel()}
        onSave={() => void save()}
        onDelete={() => setConfirmDelete(true)}
        onViewLdif={() => setLdifOpen(true)}
        onToggleAccountLock={type === 'user' ? () => void toggleAccountLock() : undefined}
      />

      {isCreate && (
        <TemplatePicker
          selected={selectedTemplate}
          onChange={setSelectedTemplate}
          disabled={!editing}
        />
      )}

      {/* Main tabbed layout */}
      <div className="flex flex-col items-start gap-4 pt-1 lg:flex-row">
        <EditorTabNav
          tabs={desc.tabs}
          currentTab={tab}
          onSelectTab={setTab}
          active={active}
          errorsByTab={errorsByTab}
          dirtyTabs={dirtyTabs}
        />

        <div
          role="tabpanel"
          id={`panel-${currentTabObj?.name}`}
          aria-labelledby={`tab-${currentTabObj?.name}`}
          className="w-full min-w-0 flex-1 space-y-4"
        >
          {currentTabObj?.optional && (
            <div className="flex items-center justify-between rounded-md border bg-card p-4">
              <div>
                <p className="text-[13px] font-medium text-foreground">
                  {t('editor.enableTab', { tab: currentTabObj.label })}
                </p>
                <p className="text-muted-foreground text-xs">{t('editor.enableTabHelp')}</p>
              </div>
              <Switch
                checked={isCurrentTabActive}
                disabled={!canToggleCurrentTab}
                onCheckedChange={(v) => {
                  if (v) {
                    for (const a of allAttributes(currentTabObj)) {
                      const key = `${currentTabObj.name}.${a.name}` as never
                      const cur = form.getValues(key) as unknown
                      if (cur === null || cur === undefined || cur === '' || (Array.isArray(cur) && cur.length === 0))
                        form.setValue(key, defaultValue(a) as never)
                    }
                  }
                  setActive((a) => ({ ...a, [currentTabObj.name]: v }))
                }}
                aria-label={t('editor.enableTab', { tab: currentTabObj.label })}
              />
            </div>
          )}

          {isCurrentTabActive &&
            currentTabObj?.sections.map((sec) => (
              <EditorSection
                key={sec.name}
                section={sec}
                tabName={currentTabObj.name}
                control={control}
                acl={detail?.acl}
                isCreate={isCreate}
                readOnlyMode={readOnlyMode}
              />
            ))}
        </div>
      </div>

      {/* Save Bar */}
      {editing && (
        <EditorSaveBar
          dirty={dirty}
          isSubmitting={formState.isSubmitting}
          isCreate={isCreate}
          changesCount={Object.keys(changes).length}
          diffs={diffs}
          onDiscard={() => void cancel()}
          onSave={() => void save()}
        />
      )}

      {/* Dialogs */}
      <LockedDialog lock={lockInfo} onClose={() => setLockInfo(null)} />

      <LdifDialog
        open={ldifOpen}
        onOpenChange={setLdifOpen}
        ldif={ldifText}
        title={title}
      />

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px] font-semibold">
              {t('editor.deleteTitle', { name: title })}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[13px] text-muted-foreground">
              {t('editor.deleteBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => void doDelete()}
            >
              {t('common.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={blocker.status === 'blocked'}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px] font-semibold">
              {t('editor.leaveTitle')}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[13px] text-muted-foreground">
              {t('editor.leaveBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => blocker.status === 'blocked' && blocker.reset()}
            >
              {t('editor.stay')}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => blocker.status === 'blocked' && blocker.proceed()}
            >
              {t('editor.leave')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </form>
  )
}

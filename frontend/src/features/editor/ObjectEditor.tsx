import { useBlocker, useNavigate } from '@tanstack/react-router'
import { AlertTriangle, Pencil, Save, Trash2, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useCreateObject, useObject, usePatchObject, useTypeDescriptor, useDeleteObjects } from '@/api/hooks'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TypeIcon } from '@/lib/icons'
import {
  activeFromDetail,
  allAttributes,
  attrRight,
  buildCreateTabs,
  computeChanges,
  defaultValue,
  deepEqual,
  nameValue,
  splitFieldKey,
  valuesFromDetail,
  type FormValues,
} from '@/lib/objects'
import { useScope } from '@/lib/scope'
import { makeResolver } from '@/lib/validation'
import { ErrorState } from '@/components/ErrorState'
import { FieldRow } from './FieldRow'
import { LockedDialog } from './LockedDialog'

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
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64 w-full" />
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desc, detail])
  const initialActive = useMemo(() => activeFromDetail(desc, detail), [desc, detail])

  const [active, setActive] = useState(initialActive)
  const activeRef = useRef(active)
  activeRef.current = active
  const [editing, setEditing] = useState(isCreate)
  const [tab, setTab] = useState(desc.tabs[0]?.name ?? 'main')
  const [lockInfo, setLockInfo] = useState<LockInfo | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
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
  const baseChanged =
    !isCreate &&
    !deepEqual(current.main?.base ?? null, baseline.current.values.main?.base ?? null) &&
    desc.tabs[0]?.sections.some((s) => s.attributes.some((a) => a.name === 'base' && a.kind === 'department'))
  const dirty = isCreate
    ? !deepEqual(current, baseline.current.values) || !deepEqual(active, baseline.current.active)
    : Object.keys(changes).length > 0 || !!baseChanged

  // ── unsaved-changes guard ────────────────────────────────────────────
  const blocker = useBlocker({
    shouldBlockFn: () => editing && dirty && !bypassGuard.current,
    withResolver: true,
    enableBeforeUnload: () => editing && dirty && !bypassGuard.current,
  })

  // release the edit lock if the page goes away while editing
  useEffect(() => {
    return () => {
      if (locked.current && detail) void api.unlockObject(type, detail.dn).catch(() => undefined)
    }
  }, [type, detail])

  const patch = usePatchObject(type, detail?.dn ?? '')
  const create = useCreateObject(type)
  const del = useDeleteObjects(type)

  const readOnlyMode = !editing
  const objectRights = detail?.acl[desc.tabs[0]?.name ?? 'main']?.object ?? 'rwcdm'
  const canEdit = isCreate || objectRights.includes('w') || objectRights.includes('m')
  const canDelete = !isCreate && objectRights.includes('d')

  const title = isCreate ? t('editor.newTitle', { type: desc.label }) : nameValue(desc, detail)

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
            template: null,
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

  const errorsByTab = formState.errors as Record<string, unknown>

  return (
    <form onSubmit={(e) => void save(e)} noValidate className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="bg-primary-soft text-primary flex size-10 shrink-0 items-center justify-center rounded-lg">
            <TypeIcon name={desc.icon} className="size-5" />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
            {detail && <p className="font-dn text-muted-foreground truncate">{detail.dn}</p>}
          </div>
          {editing && !isCreate && <Badge variant="outline">{t('editor.editing')}</Badge>}
          {dirty && editing && (
            <Badge variant="secondary" data-testid="dirty-indicator">
              {t('editor.unsaved')}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {editing ? (
            <>
              <Button type="button" variant="ghost" onClick={() => void (isCreate ? navigate({ to: '/types/$type', params: { type } }) : cancel())}>
                <X className="size-4" />
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={!dirty || formState.isSubmitting}>
                <Save className="size-4" />
                {isCreate ? t('common.create') : t('common.save')}
              </Button>
            </>
          ) : (
            <>
              {canDelete && (
                <Button type="button" variant="outline" onClick={() => setConfirmDelete(true)}>
                  <Trash2 className="size-4" />
                  {t('common.delete')}
                </Button>
              )}
              {canEdit && (
                <Button type="button" onClick={() => void startEdit()}>
                  <Pencil className="size-4" />
                  {t('common.edit')}
                </Button>
              )}
            </>
          )}
        </div>
      </header>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="h-auto flex-wrap justify-start">
          {desc.tabs.map((tb) => (
            <TabsTrigger key={tb.name} value={tb.name} className="gap-2">
              {tb.label}
              {tb.optional && !active[tb.name] && (
                <span className="text-muted-foreground text-xs">({t('editor.inactive')})</span>
              )}
              {errorsByTab[tb.name] ? (
                <AlertTriangle className="text-destructive size-3.5" aria-label={t('editor.tabHasErrors')} />
              ) : null}
            </TabsTrigger>
          ))}
        </TabsList>

        {desc.tabs.map((tb) => {
          const isActive = active[tb.name] ?? false
          const tabAcl = detail?.acl[tb.name]
          const canToggle = editing && (isCreate || !tabAcl || tabAcl.object.includes('m'))
          return (
            <TabsContent key={tb.name} value={tb.name} className="space-y-6 pt-2" forceMount={undefined}>
              {tb.optional && (
                <div className="flex items-center justify-between rounded-lg border p-4">
                  <div>
                    <p className="font-medium">{t('editor.enableTab', { tab: tb.label })}</p>
                    <p className="text-muted-foreground text-sm">{t('editor.enableTabHelp')}</p>
                  </div>
                  <Switch
                    checked={isActive}
                    disabled={!canToggle}
                    onCheckedChange={(v) => {
                      if (v) {
                        for (const a of allAttributes(tb)) {
                          const key = `${tb.name}.${a.name}` as never
                          const cur = form.getValues(key) as unknown
                          if (cur === null || cur === undefined || cur === '' || (Array.isArray(cur) && cur.length === 0))
                            form.setValue(key, defaultValue(a) as never)
                        }
                      }
                      setActive((a) => ({ ...a, [tb.name]: v }))
                    }}
                    aria-label={t('editor.enableTab', { tab: tb.label })}
                  />
                </div>
              )}
              {isActive &&
                tb.sections.map((sec) => {
                  const visible = sec.attributes.filter((a) => {
                    if (a.kind === 'hidden') return false
                    if (isCreate && a.kind === 'display') return false
                    return attrRight(detail?.acl, tb.name, a) !== 'hidden'
                  })
                  if (visible.length === 0) return null
                  return (
                    <section key={sec.name} aria-labelledby={`sec-${tb.name}-${sec.name}`} className="bg-card rounded-xl border p-5 shadow-xs">
                      <h2 id={`sec-${tb.name}-${sec.name}`} className="mb-4 text-sm font-semibold">
                        {sec.label}
                      </h2>
                      <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
                        {visible.map((a) => {
                          const right = attrRight(detail?.acl, tb.name, a)
                          // the RDN attribute can only be set at creation time via ACL; honour descriptor
                          const ro = readOnlyMode || right !== 'rw' || (a.readonly === true && !isCreate)
                          return (
                            <FieldRow key={a.name} control={control as never} tab={tb.name} attr={a} readOnly={ro} />
                          )
                        })}
                      </div>
                    </section>
                  )
                })}
            </TabsContent>
          )
        })}
      </Tabs>

      <LockedDialog lock={lockInfo} onClose={() => setLockInfo(null)} />

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('editor.deleteTitle', { name: title })}</AlertDialogTitle>
            <AlertDialogDescription>{t('editor.deleteBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
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
            <AlertDialogTitle>{t('editor.leaveTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('editor.leaveBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.status === 'blocked' && blocker.reset()}>
              {t('editor.stay')}
            </AlertDialogCancel>
            <AlertDialogAction onClick={() => blocker.status === 'blocked' && blocker.proceed()}>
              {t('editor.leave')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </form>
  )
}

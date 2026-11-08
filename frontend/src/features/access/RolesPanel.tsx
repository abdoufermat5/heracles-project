import { Check, Copy, KeyRound, Pencil, Plus, ShieldCheck, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { useMe } from '@/api/hooks'
import { ErrorState } from '@/components/ErrorState'
import { ConfirmDialog, FilterBar, OrgPath } from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { useAllAssignments, useCatalog, useRoleMutations, useRoles } from '@/features/admin/hooks'
import type { AclRole, Catalog } from '@/features/admin/types'
import { useTechnicalDetails } from '@/lib/preferences'
import { RoleEditor } from './RoleEditor'
import { roleObjectCount, summarizeRole } from './rightsModel'

function RoleCard({
  role,
  catalog,
  locations,
  onEdit,
  onDuplicate,
  onDelete,
}: {
  role: AclRole
  catalog: Catalog | undefined
  locations: string[]
  onEdit: () => void
  onDuplicate: () => void
  onDelete: () => void
}) {
  const { t } = useTranslation()
  const technical = useTechnicalDetails()
  const sentences = useMemo(() => summarizeRole(role, catalog, t), [role, catalog, t])
  const assignments = role.used_by ?? locations.length
  const shown = sentences.slice(0, 4)

  return (
    <article className="flex min-w-0 flex-col rounded-lg border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary-soft text-primary">
              <KeyRound className="size-4" aria-hidden />
            </span>
            <h3 className="truncate text-lead font-semibold text-foreground">{role.cn}</h3>
          </div>
          <p className="mt-1 text-small text-muted-foreground">
            {role.description || t('accessUI.roles.noDescription')}
          </p>
          {technical && (
            <p
              className="mt-0.5 truncate font-dn text-caption text-muted-foreground"
              title={role.dn}
            >
              {role.dn}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={t('accessUI.roles.edit', { name: role.cn })}
            onClick={onEdit}
          >
            <Pencil />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={t('accessUI.roles.duplicate', { name: role.cn })}
            onClick={onDuplicate}
          >
            <Copy />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={t('accessUI.roles.remove', { name: role.cn })}
            onClick={onDelete}
          >
            <Trash2 />
          </Button>
        </div>
      </div>

      <div className="mt-3 flex-1">
        {shown.length === 0 ? (
          <p className="text-small text-muted-foreground">{t('accessUI.roles.summaryEmpty')}</p>
        ) : (
          <ul className="space-y-1.5">
            {shown.map((sentence) => (
              <li key={sentence} className="flex gap-1.5 text-small">
                <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />
                <span>{sentence}</span>
              </li>
            ))}
            {sentences.length > shown.length && (
              <li className="pl-5 text-caption text-muted-foreground">
                {t('accessUI.roles.more', { count: sentences.length - shown.length })}
              </li>
            )}
          </ul>
        )}
      </div>

      <footer className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-3 text-caption text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <ShieldCheck className="size-3.5" aria-hidden />
          {t('accessUI.roles.assignments', { count: assignments })}
        </span>
        <span aria-hidden>·</span>
        <span>{t('accessUI.roles.objects', { count: roleObjectCount(role) })}</span>
        {assignments === 0 && <span className="ml-auto">{t('accessUI.roles.unused')}</span>}
      </footer>
    </article>
  )
}

export function RolesPanel() {
  const { t } = useTranslation()
  const { data: me } = useMe()
  const { data, isPending, isError, error, refetch } = useRoles()
  const { data: catalog } = useCatalog()
  const { data: allAssignments } = useAllAssignments()
  const { remove } = useRoleMutations()
  const [search, setSearch] = useState('')
  const [editor, setEditor] = useState<{ role: AclRole | null; duplicate?: AclRole | null } | null>(
    null,
  )
  const [deleting, setDeleting] = useState<AclRole | null>(null)

  const usesByRole = useMemo(() => {
    const map = new Map<string, string[]>()
    for (const entry of allAssignments ?? []) {
      for (const assignment of entry.assignments) {
        if (assignment.ignored || !assignment.role) continue
        const current = map.get(assignment.role) ?? []
        if (!current.includes(entry.dn)) current.push(entry.dn)
        map.set(assignment.role, current)
      }
    }
    return map
  }, [allAssignments])

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />

  const query = search.trim().toLowerCase()
  const roles = (data ?? []).filter(
    (role) =>
      query === '' ||
      role.cn.toLowerCase().includes(query) ||
      role.description.toLowerCase().includes(query),
  )
  const deleteLocations = deleting ? (usesByRole.get(deleting.dn) ?? []) : []

  const confirmDelete = async () => {
    if (!deleting) return
    try {
      await remove.mutateAsync({ dn: deleting.dn, force: deleteLocations.length > 0 })
      toast.success(t('accessUI.roles.deleted'))
      setDeleting(null)
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-body text-muted-foreground">{t('accessUI.roles.help')}</p>
        <Button size="sm" onClick={() => setEditor({ role: null })}>
          <Plus />
          {t('accessUI.roles.new')}
        </Button>
      </div>
      <FilterBar
        search={search}
        onSearch={setSearch}
        placeholder={t('accessUI.roles.search')}
      />

      {isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : (data ?? []).length === 0 ? (
        <EmptyState
          icon={<KeyRound />}
          title={t('accessUI.roles.empty')}
          description={t('accessUI.roles.emptyHelp')}
          action={
            <Button size="sm" onClick={() => setEditor({ role: null })}>
              <Plus />
              {t('accessUI.roles.new')}
            </Button>
          }
        />
      ) : roles.length === 0 ? (
        <EmptyState icon={<KeyRound />} title={t('accessUI.roles.noResults')} />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {roles.map((role) => (
            <RoleCard
              key={role.dn}
              role={role}
              catalog={catalog}
              locations={usesByRole.get(role.dn) ?? []}
              onEdit={() => setEditor({ role })}
              onDuplicate={() => setEditor({ role: null, duplicate: role })}
              onDelete={() => setDeleting(role)}
            />
          ))}
        </div>
      )}

      {editor && (
        <RoleEditor
          key={(editor.role?.dn ?? 'new') + (editor.duplicate?.dn ?? '')}
          open
          role={editor.role}
          duplicate={editor.duplicate ?? null}
          onOpenChange={(open) => {
            if (!open) setEditor(null)
          }}
        />
      )}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null)
        }}
        title={t('accessUI.roles.deleteTitle', { name: deleting?.cn ?? '' })}
        description={
          deleteLocations.length > 0
            ? t('accessUI.roles.deleteInUse', { count: deleteLocations.length })
            : t('accessUI.roles.deleteUnused')
        }
        confirmLabel={t('accessUI.roles.deleteConfirm')}
        destructive
        pending={remove.isPending}
        onConfirm={() => void confirmDelete()}
      >
        {deleteLocations.length > 0 && (
          <ul className="space-y-1.5 text-small">
            {deleteLocations.map((dn) => (
              <li key={dn} className="flex items-center gap-1.5">
                <OrgPath dn={dn} baseDn={me?.base} />
              </li>
            ))}
          </ul>
        )}
      </ConfirmDialog>
    </div>
  )
}

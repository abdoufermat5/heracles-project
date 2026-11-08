import { Plus, ShieldAlert, Trash2, UserRound } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { useMe } from '@/api/hooks'
import { ErrorState } from '@/components/ErrorState'
import { ConfirmDialog, FilterBar, FilterChip, OrgPath } from '@/components/patterns'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { useAllAssignments, useRoles, useSaveEntryAssignments } from '@/features/admin/hooks'
import { nextIndex } from '@/features/admin/rights'
import type { Assignment, AssignmentMember } from '@/features/admin/types'
import { orgPath } from '@/lib/dn'
import { rdnValue } from '@/lib/objects'
import { useTechnicalDetails } from '@/lib/preferences'
import { AssignmentDialog } from './AssignmentDialog'
import { memberLabel, normaliseMembers } from './peopleModel'

interface AccessRow {
  id: string
  entryDn: string
  assignment: Assignment
  member: AssignmentMember
}

function renumber(items: Assignment[]): Assignment[] {
  return items.map((assignment, index) =>
    assignment.ignored ? assignment : { ...assignment, index },
  )
}

export function WhoHasAccessPanel() {
  const { t } = useTranslation()
  const technical = useTechnicalDetails()
  const { data: me } = useMe()
  const { data, isPending, isError, error, refetch } = useAllAssignments()
  const { data: roles } = useRoles()
  const save = useSaveEntryAssignments()
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState<string[]>([])
  const [departmentFilter, setDepartmentFilter] = useState<string[]>([])
  const [typeFilter, setTypeFilter] = useState<string[]>([])
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<AccessRow | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const rows = useMemo(() => {
    const out: AccessRow[] = []
    for (const entry of data ?? []) {
      for (const assignment of entry.assignments) {
        if (assignment.ignored) continue
        for (const member of normaliseMembers(assignment)) {
          out.push({
            id: `${entry.dn}|${assignment.index}|${member.dn}`,
            entryDn: entry.dn,
            assignment,
            member,
          })
        }
      }
    }
    return out
  }, [data])

  const roleOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const row of rows) {
      const key = row.assignment.role ?? ''
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    return [...counts.entries()].map(([dn, count]) => ({
      value: dn,
      label:
        roles?.find((role) => role.dn === dn)?.cn ??
        rows.find((row) => row.assignment.role === dn)?.assignment.role_name ??
        (dn === '' ? t('accessUI.people.missingRole') : rdnValue(dn)),
      count,
    }))
  }, [rows, roles, t])

  const departmentOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const row of rows) counts.set(row.entryDn, (counts.get(row.entryDn) ?? 0) + 1)
    return [...counts.entries()].map(([dn, count]) => ({
      value: dn,
      label: orgPath(dn, me?.base, true).join(' › ') || t('patterns.topLevel'),
      count,
    }))
  }, [rows, me?.base, t])

  const typeOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const row of rows) counts.set(row.member.kind, (counts.get(row.member.kind) ?? 0) + 1)
    return [...counts.entries()].map(([kind, count]) => ({
      value: kind,
      label: t(`accessUI.people.kind.${kind}`),
      count,
    }))
  }, [rows, t])

  const query = search.trim().toLowerCase()
  const visible = rows.filter((row) => {
    if (roleFilter.length > 0 && !roleFilter.includes(row.assignment.role ?? '')) return false
    if (departmentFilter.length > 0 && !departmentFilter.includes(row.entryDn)) return false
    if (typeFilter.length > 0 && !typeFilter.includes(row.member.kind)) return false
    if (query === '') return true
    const haystack = [
      memberLabel(row.member, t('accessUI.people.everyone')),
      row.assignment.role_name ?? '',
      rdnValue(row.assignment.role ?? ''),
      orgPath(row.entryDn, me?.base, true).join(' '),
      row.member.dn,
    ]
      .join(' ')
      .toLowerCase()
    return haystack.includes(query)
  })

  if (isError && !(isApiError(error) && error.status === 404)) {
    return <ErrorState error={error} onRetry={() => void refetch()} />
  }

  const assignmentsOn = (dn: string): Assignment[] =>
    data?.find((entry) => entry.dn === dn)?.assignments ?? []

  const addAccess = async (item: Assignment, department: string) => {
    setErrors({})
    try {
      await save.mutateAsync({
        dn: department,
        items: renumber([
          ...assignmentsOn(department),
          { ...item, index: nextIndex(assignmentsOn(department)) },
        ]),
      })
      toast.success(t('accessUI.people.added'))
      setAdding(false)
    } catch (e) {
      if (isApiError(e) && e.fields) {
        const mapped: Record<string, string> = {}
        for (const [key, value] of Object.entries(e.fields))
          mapped[key.split('.').pop() ?? key] = value
        setErrors(mapped)
      }
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const removeAccess = async () => {
    if (!removing) return
    const list = assignmentsOn(removing.entryDn)
    const target = list.find((item) => item.index === removing.assignment.index)
    if (!target) {
      setRemoving(null)
      return
    }
    const members = normaliseMembers(target).filter((m) => m.dn !== removing.member.dn)
    const next =
      members.length === 0
        ? list.filter((item) => item !== target)
        : list.map((item) => (item === target ? { ...item, members } : item))
    try {
      await save.mutateAsync({ dn: removing.entryDn, items: renumber(next) })
      toast.success(t('accessUI.people.removed'))
      setRemoving(null)
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-body text-muted-foreground">{t('accessUI.people.help')}</p>
        <Button size="sm" onClick={() => setAdding(true)}>
          <Plus />
          {t('accessUI.people.add')}
        </Button>
      </div>

      <FilterBar
        search={search}
        onSearch={setSearch}
        placeholder={t('accessUI.people.search')}
      >
        <FilterChip
          label={t('accessUI.people.filters.role')}
          options={roleOptions}
          selected={roleFilter}
          onChange={setRoleFilter}
        />
        <FilterChip
          label={t('accessUI.people.filters.department')}
          options={departmentOptions}
          selected={departmentFilter}
          onChange={setDepartmentFilter}
        />
        <FilterChip
          label={t('accessUI.people.filters.memberType')}
          options={typeOptions}
          selected={typeFilter}
          onChange={setTypeFilter}
        />
      </FilterBar>

      {isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<UserRound />}
          title={t('accessUI.people.noAccess')}
          description={t('accessUI.people.noAccessHelp')}
          action={
            <Button size="sm" onClick={() => setAdding(true)}>
              <Plus />
              {t('accessUI.people.add')}
            </Button>
          }
        />
      ) : visible.length === 0 ? (
        <EmptyState icon={<ShieldAlert />} title={t('accessUI.people.noResults')} />
      ) : (
        <ul className="space-y-2">
          {visible.map((row) => {
            const name = memberLabel(row.member, t('accessUI.people.everyone'))
            const roleName =
              row.assignment.role_name ?? roles?.find((r) => r.dn === row.assignment.role)?.cn ?? '—'
            return (
              <li key={row.id} className="rounded-lg border bg-card p-3">
                <div className="grid gap-3 md:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)_minmax(0,1fr)_auto_auto] md:items-center">
                  <div className="min-w-0">
                    <div className="text-caption text-muted-foreground md:hidden">
                      {t('accessUI.people.who')}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="truncate text-body font-medium text-foreground">
                        {name}
                      </span>
                      <Badge variant={row.member.kind === 'missing' ? 'destructive' : 'secondary'}>
                        {t(`accessUI.people.kind.${row.member.kind}`)}
                      </Badge>
                    </div>
                    {technical && (
                      <p
                        className="truncate font-dn text-caption text-muted-foreground"
                        title={row.member.dn}
                      >
                        {row.member.dn}
                      </p>
                    )}
                  </div>

                  <div className="min-w-0">
                    <div className="text-caption text-muted-foreground md:hidden">
                      {t('accessUI.people.role')}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="truncate text-body">{roleName}</span>
                      {row.assignment.role_missing && (
                        <Badge variant="destructive">{t('accessUI.people.missingRole')}</Badge>
                      )}
                    </div>
                    {technical && row.assignment.role && (
                      <p
                        className="truncate font-dn text-caption text-muted-foreground"
                        title={row.assignment.role}
                      >
                        {row.assignment.role}
                      </p>
                    )}
                  </div>

                  <div className="min-w-0">
                    <div className="text-caption text-muted-foreground md:hidden">
                      {t('accessUI.people.where')}
                    </div>
                    <OrgPath dn={row.entryDn} baseDn={me?.base} includeSelf />
                  </div>

                  <div>
                    <div className="text-caption text-muted-foreground md:hidden">
                      {t('accessUI.people.scope')}
                    </div>
                    <Badge variant="outline">
                      {row.assignment.scope === 'base'
                        ? t('accessUI.people.scopeBaseShort')
                        : t('accessUI.people.scopeSubtreeShort')}
                    </Badge>
                  </div>

                  <div className="flex justify-end">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t('accessUI.people.remove', { name })}
                      onClick={() => setRemoving(row)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {adding && (
        <AssignmentDialog
          open
          defaultDepartment={me?.base ?? null}
          errors={errors}
          onOpenChange={(open) => {
            if (!open) {
              setAdding(false)
              setErrors({})
            }
          }}
          onSave={(item, department) => void addAccess(item, department)}
        />
      )}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null)
        }}
        title={t('accessUI.people.removeTitle')}
        description={
          removing
            ? t('accessUI.people.removeHelp', {
                name: memberLabel(removing.member, t('accessUI.people.everyone')),
                role:
                  removing.assignment.role_name ??
                  roles?.find((r) => r.dn === removing.assignment.role)?.cn ??
                  '—',
                where:
                  orgPath(removing.entryDn, me?.base, true).join(' › ') ||
                  t('patterns.topLevel'),
              })
            : undefined
        }
        confirmLabel={t('common.delete')}
        destructive
        pending={save.isPending}
        onConfirm={() => void removeAccess()}
      />
    </div>
  )
}

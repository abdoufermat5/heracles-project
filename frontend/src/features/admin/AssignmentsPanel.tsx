import { ArrowDown, ArrowUp, Pencil, Plus, ShieldAlert, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { useMe } from '@/api/hooks'
import { ErrorState } from '@/components/ErrorState'
import { DepartmentPicker } from '@/components/fields/RefFields'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { rdnValue } from '@/lib/objects'
import { AssignmentDialog } from './AssignmentDialog'
import { useAssignments, useSaveAssignments } from './hooks'
import { memberDns, nextIndex } from './rights'
import type { Assignment } from './types'

function renumber(items: Assignment[]): Assignment[] {
  return items.map((a, i) => (a.ignored ? a : { ...a, index: i }))
}

export function AssignmentsPanel() {
  const { t } = useTranslation()
  const { data: me } = useMe()
  const [picked, setDn] = useState<string | null>(null)
  const dn = picked ?? me?.base ?? null

  const { data, isPending, isError, error, refetch } = useAssignments(dn)
  const save = useSaveAssignments(dn ?? '')
  const [editing, setEditing] = useState<{ item: Assignment; position: number } | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  if (isError && !isApiErrorNotFound(error)) return <ErrorState error={error} onRetry={() => void refetch()} />

  const items = data?.assignments ?? []

  const persist = async (next: Assignment[]): Promise<boolean> => {
    setErrors({})
    try {
      await save.mutateAsync(next)
      toast.success(t('acl.assignmentsSaved'))
      return true
    } catch (e) {
      if (isApiError(e) && e.fields) {
        const mapped: Record<string, string> = {}
        for (const [k, v] of Object.entries(e.fields)) mapped[k.split('.').pop() ?? k] = v
        setErrors(mapped)
      }
      toast.error(isApiError(e) ? e.message : t('common.error'))
      return false
    }
  }

  const move = (i: number, delta: -1 | 1) => {
    const next = [...items]
    const target = i + delta
    const a = next[i]
    const b = next[target]
    if (!a || !b) return
    next[i] = b
    next[target] = a
    void persist(renumber(next))
  }

  const onSave = async (item: Assignment) => {
    if (!editing) return
    const next =
      editing.position >= items.length
        ? [...items, item]
        : items.map((x, i) => (i === editing.position ? item : x))
    if (await persist(next)) setEditing(null)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <Label htmlFor="asg-department">{t('acl.assignmentsOn')}</Label>
          <DepartmentPicker id="asg-department" value={dn} onChange={setDn} />
        </div>
        <Button
          size="sm"
          disabled={dn === null}
          onClick={() =>
            setEditing({
              position: items.length,
              item: { index: nextIndex(items), scope: 'subtree', members: [] },
            })
          }
        >
          <Plus />
          {t('acl.addAssignment')}
        </Button>
      </div>
      <p className="text-[13px] text-muted-foreground">{t('acl.assignmentsHelp')}</p>

      {isPending && dn !== null ? (
        <Skeleton className="h-32 w-full" />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<ShieldAlert />}
          title={t('acl.noAssignments')}
          description={t('acl.noAssignmentsHelp')}
        />
      ) : (
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">{t('acl.priority')}</TableHead>
                <TableHead>{t('acl.role')}</TableHead>
                <TableHead>{t('acl.scope')}</TableHead>
                <TableHead>{t('acl.members')}</TableHead>
                <TableHead>{t('acl.filters')}</TableHead>
                <TableHead className="w-36" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((a, i) =>
                a.ignored ? (
                  <TableRow key={a.raw ?? i}>
                    <TableCell className="font-mono text-xs">—</TableCell>
                    <TableCell colSpan={4}>
                      <span className="text-[13px] text-muted-foreground">
                        {t('acl.unreadableAssignment')}
                      </span>
                      <div className="font-mono text-[11px] break-all text-muted-foreground">
                        {a.raw}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t('common.delete')}
                        onClick={() => void persist(items.filter((_, j) => j !== i))}
                      >
                        <Trash2 />
                      </Button>
                    </TableCell>
                  </TableRow>
                ) : (
                  <TableRow key={a.raw ?? i}>
                    <TableCell className="font-mono text-xs tabular-nums">{a.index}</TableCell>
                    <TableCell>
                      <span className="font-medium">{a.role_name ?? rdnValue(a.role ?? '')}</span>
                      {a.role_missing && (
                        <Badge variant="destructive" className="ml-2">
                          {t('acl.roleMissing')}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">
                        {a.scope === 'base' ? t('acl.scopeBaseShort') : t('acl.scopeSubtreeShort')}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {(a.members ?? []).map((m) => {
                          const dnValue = typeof m === 'string' ? m : m.dn
                          const kind = typeof m === 'string' ? '' : m.kind
                          return (
                            <Badge key={dnValue} variant={kind === 'missing' ? 'destructive' : 'secondary'}>
                              {dnValue === '*' ? t('acl.everyone') : rdnValue(dnValue)}
                              {kind && kind !== 'everyone' && (
                                <span className="ml-1 opacity-70">{t(`acl.kind.${kind}`)}</span>
                              )}
                            </Badge>
                          )
                        })}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-[11px] text-muted-foreground">
                      {a.user_filter && <div>{t('acl.userFilterShort')}: {a.user_filter}</div>}
                      {a.target_filter && <div>{t('acl.targetFilterShort')}: {a.target_filter}</div>}
                      {!a.user_filter && !a.target_filter && '—'}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        disabled={i === 0}
                        aria-label={t('acl.moveUp', { name: a.role_name ?? '' })}
                        onClick={() => move(i, -1)}
                      >
                        <ArrowUp />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        disabled={i === items.length - 1}
                        aria-label={t('acl.moveDown', { name: a.role_name ?? '' })}
                        onClick={() => move(i, 1)}
                      >
                        <ArrowDown />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t('acl.editAssignment', { name: a.role_name ?? '' })}
                        onClick={() => setEditing({ item: a, position: i })}
                      >
                        <Pencil />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t('acl.deleteAssignment', { name: a.role_name ?? '' })}
                        onClick={() => void persist(renumber(items.filter((_, j) => j !== i)))}
                      >
                        <Trash2 />
                      </Button>
                    </TableCell>
                  </TableRow>
                ),
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {editing && (
        <AssignmentDialog
          key={`${editing.position}-${memberDns(editing.item).join(',')}`}
          open
          initial={editing.item}
          errors={errors}
          onOpenChange={(o) => {
            if (!o) setEditing(null)
          }}
          onSave={(item) => void onSave(item)}
        />
      )}
    </div>
  )
}

function isApiErrorNotFound(e: unknown): boolean {
  return isApiError(e) && e.status === 404
}

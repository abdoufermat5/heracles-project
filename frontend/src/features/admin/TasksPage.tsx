import { ListChecks, Play, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { ErrorState } from '@/components/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/ui/page-header'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDateTime } from './format'
import { useTaskActions, useTasks } from './hooks'
import type { TaskRow } from './types'

const ALL = '__all__'
const KNOWN_STATUSES = ['Activated', 'Deactivated']

function statusVariant(status: string): 'success' | 'neutral' | 'warning' {
  const s = status.toLowerCase()
  if (s === 'activated') return 'success'
  if (s === 'deactivated') return 'neutral'
  return 'warning'
}

function Progression({ row }: { row: TaskRow }) {
  const { t } = useTranslation()
  const { total, done, failed } = row.subtasks
  if (total === 0) return <span className="text-muted-foreground">—</span>
  return (
    <div className="min-w-32 space-y-1">
      <Progress
        value={Math.round((done / total) * 100)}
        aria-label={t('tasks.progress', { done, total })}
      />
      <p className="text-caption tabular-nums text-muted-foreground">
        {t('tasks.progress', { done, total })}
        {failed > 0 && <span className="ml-1 text-destructive">· {t('tasks.failedCount', { count: failed })}</span>}
      </p>
    </div>
  )
}

export function TasksPage() {
  const { t, i18n } = useTranslation()
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const everything = useTasks('', '')
  const filtered = useTasks(kind, status)
  const { run, retry } = useTaskActions()

  const statuses = [
    ...new Set([...KNOWN_STATUSES, ...(everything.data?.tasks ?? []).map((r) => r.status).filter(Boolean)]),
  ]
  const view = filtered.data
  const summary = everything.data?.summary

  const act = async (kindOfAction: 'run' | 'retry', row: TaskRow) => {
    try {
      if (kindOfAction === 'run') {
        await run.mutateAsync(row.dn)
        toast.success(t('tasks.queued', { name: row.name }))
      } else {
        const out = await retry.mutateAsync(row.dn)
        toast.success(t('tasks.retried', { count: out.retried.length }))
      }
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  return (
    <div>
      <PageHeader title={t('tasks.title')} description={t('tasks.description')} />
      {filtered.isError ? (
        <ErrorState error={filtered.error} onRetry={() => void filtered.refetch()} />
      ) : (
        <div className="space-y-3">
          {summary && (
            <p className="flex flex-wrap items-center gap-2 text-body text-muted-foreground" aria-live="polite">
              <Badge variant="neutral">{t('tasks.total', { count: summary.total })}</Badge>
              <Badge variant="success">{t('tasks.active', { count: summary.active })}</Badge>
              <Badge variant={summary.failed_subtasks > 0 ? 'destructive' : 'neutral'}>
                {t('tasks.failedSubtasks', { count: summary.failed_subtasks })}
              </Badge>
            </p>
          )}
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label htmlFor="tasks-kind">{t('tasks.kind')}</Label>
              <Select value={kind || ALL} onValueChange={(v) => setKind(v === ALL ? '' : v)}>
                <SelectTrigger id="tasks-kind" className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t('tasks.allKinds')}</SelectItem>
                  {(everything.data?.kinds ?? []).map((k) => (
                    <SelectItem key={k.name} value={k.name}>
                      {k.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="tasks-status">{t('tasks.status')}</Label>
              <Select value={status || ALL} onValueChange={(v) => setStatus(v === ALL ? '' : v)}>
                <SelectTrigger id="tasks-status" className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t('tasks.allStatuses')}</SelectItem>
                  {statuses.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {filtered.isPending || !view ? (
            <Skeleton className="h-48 w-full" />
          ) : view.tasks.length === 0 ? (
            <EmptyState
              icon={<ListChecks />}
              title={t('tasks.none')}
              description={kind || status ? t('tasks.noneFiltered') : t('tasks.noneHelp')}
            />
          ) : (
            <div className="rounded-md border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('tasks.name')}</TableHead>
                    <TableHead>{t('tasks.kind')}</TableHead>
                    <TableHead>{t('tasks.status')}</TableHead>
                    <TableHead>{t('tasks.lastRun')}</TableHead>
                    <TableHead>{t('tasks.nextRun')}</TableHead>
                    <TableHead>{t('tasks.subtasks')}</TableHead>
                    <TableHead className="w-28" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {view.tasks.map((row) => (
                    <TableRow key={row.dn} data-task={row.name}>
                      <TableCell className="font-medium">{row.name}</TableCell>
                      <TableCell>{row.kind_label}</TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(row.status)}>{row.status || '—'}</Badge>
                      </TableCell>
                      <TableCell className="text-body tabular-nums text-muted-foreground">
                        {formatDateTime(row.last_run, i18n.language)}
                      </TableCell>
                      <TableCell className="text-body tabular-nums text-muted-foreground">
                        {formatDateTime(row.next_run, i18n.language)}
                      </TableCell>
                      <TableCell>
                        <Progression row={row} />
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          disabled={!row.can_run || run.isPending}
                          aria-label={t('tasks.runNow', { name: row.name })}
                          title={t('tasks.runNow', { name: row.name })}
                          onClick={() => void act('run', row)}
                        >
                          <Play />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          disabled={!row.can_run || row.subtasks.failed === 0 || retry.isPending}
                          aria-label={t('tasks.retryFailed', { name: row.name })}
                          title={t('tasks.retryFailed', { name: row.name })}
                          onClick={() => void act('retry', row)}
                        >
                          <RotateCcw />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

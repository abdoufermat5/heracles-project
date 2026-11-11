import {
  CheckCircle2,
  ListChecks,
  MinusCircle,
  PauseCircle,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  X,
} from 'lucide-react'
import { useNavigate } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { ErrorState } from '@/components/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
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
import { useTaskActions, useTaskRuns, useTasks } from './hooks'
import type { TaskReport, TaskRow, TaskRun } from './types'

const ALL = '__all__'
const KNOWN_STATUSES = ['Activated', 'Deactivated']

function TaskStatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase()
  if (s === 'activated') {
    return (
      <Badge variant="success" className="gap-1">
        <CheckCircle2 className="size-3" aria-hidden />
        {status}
      </Badge>
    )
  }
  if (s === 'deactivated') {
    return (
      <Badge variant="neutral" className="gap-1">
        <PauseCircle className="size-3" aria-hidden />
        {status}
      </Badge>
    )
  }
  return (
    <Badge variant="warning" className="gap-1">
      <MinusCircle className="size-3" aria-hidden />
      {status || '—'}
    </Badge>
  )
}

function RunStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation()
  const label = t(`tasks.runStatus.${status}`, { defaultValue: status })
  const variant = status === 'ok' ? 'success' : status === 'error' ? 'destructive' : 'warning'
  return <Badge variant={variant}>{label}</Badge>
}

function LastReport({ report }: { report: TaskReport | null | undefined }) {
  const { t, i18n } = useTranslation()
  if (!report) return <span className="text-muted-foreground">{t('tasks.noReport')}</span>
  return (
    <div className="space-y-0.5" title={report.errors.join('\n') || undefined}>
      <RunStatusBadge status={report.status} />
      <p className="text-caption text-muted-foreground">
        {report.summary} · {formatDateTime(report.time, i18n.language)}
      </p>
    </div>
  )
}

function NewTaskButton({ kinds }: { kinds: { name: string; label: string }[] }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [kind, setKind] = useState('')
  return (
    <div className="flex items-end gap-2">
      <div className="space-y-1">
        <Label htmlFor="tasks-new-kind" className="text-caption font-medium">
          {t('tasks.newTaskKind')}
        </Label>
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger id="tasks-new-kind" className="h-8 w-56 text-small">
            <SelectValue placeholder={t('tasks.newTaskPick')} />
          </SelectTrigger>
          <SelectContent>
            {kinds.map((k) => (
              <SelectItem key={k.name} value={k.name}>
                {k.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Button
        size="sm"
        className="h-8"
        disabled={!kind}
        onClick={() => void navigate({ to: '/types/$type/new', params: { type: kind } })}
      >
        <Plus className="size-3.5 mr-1" aria-hidden />
        {t('tasks.newTask')}
      </Button>
    </div>
  )
}

function RecentRuns({ history }: { history: boolean }) {
  const { t, i18n } = useTranslation()
  const runs = useTaskRuns()
  const list: TaskRun[] = runs.data?.runs ?? []
  return (
    <section className="space-y-2" aria-labelledby="tasks-runs-title">
      <div className="flex items-center justify-between">
        <div>
          <h2 id="tasks-runs-title" className="text-h3 font-semibold">
            {t('tasks.recentRuns')}
          </h2>
          <p className="text-caption text-muted-foreground">{t('tasks.recentRunsHelp')}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void runs.refetch()}>
          <RefreshCw className="size-3.5 mr-1" aria-hidden />
          {t('tasks.refresh')}
        </Button>
      </div>
      {runs.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : list.length === 0 ? (
        <p className="rounded-md border bg-card p-3 text-small text-muted-foreground">
          {history ? t('tasks.runsNone') : t('tasks.runsNoHistory')}
        </p>
      ) : (
        <div className="rounded-md border bg-card shadow-2xs">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('tasks.started')}</TableHead>
                <TableHead>{t('tasks.runner')}</TableHead>
                <TableHead>{t('tasks.status')}</TableHead>
                <TableHead>{t('tasks.result')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((r) => (
                <TableRow key={r.id} data-run={r.runner}>
                  <TableCell className="tabular-nums text-muted-foreground">
                    {formatDateTime(r.started, i18n.language)}
                  </TableCell>
                  <TableCell className="font-medium">{r.runner}</TableCell>
                  <TableCell>
                    <RunStatusBadge status={r.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {r.summary}
                    {r.errors.length > 0 && (
                      <span className="block text-caption text-destructive">{r.errors[0]}</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  )
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
        {failed > 0 && (
          <span className="ml-1 text-destructive font-medium">
            · {t('tasks.failedCount', { count: failed })}
          </span>
        )}
      </p>
    </div>
  )
}

export function TasksPage() {
  const { t, i18n } = useTranslation()
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')

  const everything = useTasks('', '')
  const filtered = useTasks(kind, status)
  const { run, retry } = useTaskActions()

  const statuses = [
    ...new Set([
      ...KNOWN_STATUSES,
      ...(everything.data?.tasks ?? []).map((r) => r.status).filter(Boolean),
    ]),
  ]
  const view = filtered.data
  const summary = everything.data?.summary

  const tasksToDisplay = useMemo(() => {
    const list = view?.tasks ?? []
    if (!search.trim()) return list
    const q = search.trim().toLowerCase()
    return list.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.kind_label.toLowerCase().includes(q) ||
        r.dn.toLowerCase().includes(q),
    )
  }, [view?.tasks, search])

  const act = async (kindOfAction: 'run' | 'retry', row: TaskRow) => {
    try {
      if (kindOfAction === 'run') {
        const out = await run.mutateAsync(row.dn)
        const mine = out.runs.find((r) => r.kind === row.kind)
        toast.success(
          out.queued || !mine
            ? t('tasks.queued', { name: row.name })
            : t('tasks.ran', { name: row.name, summary: mine.summary }),
        )
      } else {
        const out = await retry.mutateAsync(row.dn)
        toast.success(t('tasks.retried', { count: out.retried.length }))
      }
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const hasActiveFilters = Boolean(kind || status || search)

  return (
    <div className="space-y-4">
      <PageHeader title={t('tasks.title')} description={t('tasks.description')} />
      {everything.data?.capabilities && !everything.data.capabilities.scheduler_in_process && (
        <p className="rounded-md border bg-card p-3 text-small text-muted-foreground" role="note">
          {t('tasks.noScheduler')}
        </p>
      )}
      {(everything.data?.kinds.length ?? 0) > 0 && <NewTaskButton kinds={everything.data?.kinds ?? []} />}
      {filtered.isError ? (
        <ErrorState error={filtered.error} onRetry={() => void filtered.refetch()} />
      ) : (
        <div className="space-y-4">
          {summary && (
            <div className="flex flex-wrap items-center gap-2" aria-live="polite">
              <Badge variant="neutral">
                {t('tasks.total', { count: summary.total })}
              </Badge>
              <Badge variant="success">
                {t('tasks.active', { count: summary.active })}
              </Badge>
              <Badge variant={summary.failed_subtasks > 0 ? 'destructive' : 'neutral'}>
                {t('tasks.failedSubtasks', { count: summary.failed_subtasks })}
              </Badge>
            </div>
          )}

          {/* Filters Bar */}
          <div className="flex flex-wrap items-end gap-3 rounded-md border bg-card p-3 shadow-2xs">
            <div className="space-y-1">
              <Label htmlFor="tasks-search" className="text-caption font-medium">
                {t('shell.search')}
              </Label>
              <div className="relative w-56">
                <Search
                  className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <Input
                  id="tasks-search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('settingsUI.tasks.search')}
                  className="h-8 pl-8 pr-7 text-small"
                />
                {search && (
                  <button
                    type="button"
                    onClick={() => setSearch('')}
                    className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    aria-label={t('settingsUI.config.clearSearch')}
                  >
                    <X className="size-3.5" />
                  </button>
                )}
              </div>
            </div>

            <div className="space-y-1">
              <Label htmlFor="tasks-kind" className="text-caption font-medium">
                {t('tasks.kind')}
              </Label>
              <Select value={kind || ALL} onValueChange={(v) => setKind(v === ALL ? '' : v)}>
                <SelectTrigger id="tasks-kind" className="h-8 w-56 text-small">
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
              <Label htmlFor="tasks-status" className="text-caption font-medium">
                {t('tasks.status')}
              </Label>
              <Select value={status || ALL} onValueChange={(v) => setStatus(v === ALL ? '' : v)}>
                <SelectTrigger id="tasks-status" className="h-8 w-44 text-small">
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

            {hasActiveFilters && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 text-small text-muted-foreground hover:text-foreground"
                onClick={() => {
                  setKind('')
                  setStatus('')
                  setSearch('')
                }}
              >
                <X className="size-3.5 mr-1" />
                {t('settingsUI.tasks.clearFilters')}
              </Button>
            )}
          </div>

          {filtered.isPending || !view ? (
            <Skeleton className="h-48 w-full" />
          ) : tasksToDisplay.length === 0 ? (
            <EmptyState
              icon={<ListChecks className="size-6 text-muted-foreground" aria-hidden />}
              title={t('tasks.none')}
              description={
                hasActiveFilters ? t('tasks.noneFiltered') : t('tasks.noneHelp')
              }
              action={
                hasActiveFilters ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setKind('')
                      setStatus('')
                      setSearch('')
                    }}
                  >
                    {t('settingsUI.tasks.clearFilters')}
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <div className="rounded-md border bg-card shadow-2xs">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('tasks.name')}</TableHead>
                    <TableHead>{t('tasks.kind')}</TableHead>
                    <TableHead>{t('tasks.status')}</TableHead>
                    <TableHead>{t('tasks.lastRun')}</TableHead>
                    <TableHead>{t('tasks.nextRun')}</TableHead>
                    <TableHead>{t('tasks.lastReport')}</TableHead>
                    <TableHead>{t('tasks.subtasks')}</TableHead>
                    <TableHead className="w-28 text-right" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tasksToDisplay.map((row) => (
                    <TableRow key={row.dn} data-task={row.name}>
                      <TableCell className="font-medium text-foreground">
                        {row.name}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {row.kind_label}
                      </TableCell>
                      <TableCell>
                        <TaskStatusBadge status={row.status} />
                      </TableCell>
                      <TableCell className="text-body tabular-nums text-muted-foreground">
                        {formatDateTime(row.last_run, i18n.language)}
                      </TableCell>
                      <TableCell className="text-body tabular-nums text-muted-foreground">
                        {formatDateTime(row.next_run, i18n.language)}
                      </TableCell>
                      <TableCell>
                        <LastReport report={row.last_report} />
                      </TableCell>
                      <TableCell>
                        <Progression row={row} />
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            disabled={!row.can_run || run.isPending}
                            aria-label={t('tasks.runNow', { name: row.name })}
                            title={t('tasks.runNow', { name: row.name })}
                            onClick={() => void act('run', row)}
                          >
                            <Play className="size-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            disabled={!row.can_run || row.subtasks.failed === 0 || retry.isPending}
                            aria-label={t('tasks.retryFailed', { name: row.name })}
                            title={t('tasks.retryFailed', { name: row.name })}
                            onClick={() => void act('retry', row)}
                          >
                            <RotateCcw className="size-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          <RecentRuns history={everything.data?.capabilities?.run_history ?? false} />
          {everything.data?.capabilities && (
            <p className="text-caption text-muted-foreground">
              {everything.data.capabilities.syslog_configured ? t('tasks.syslogOn') : t('tasks.syslogOff')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

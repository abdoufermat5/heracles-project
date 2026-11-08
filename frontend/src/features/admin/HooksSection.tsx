import { Pencil, Plus, Save, TriangleAlert, Trash2, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { ErrorState } from '@/components/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Workflow } from 'lucide-react'
import { useHooks, useSaveHooks } from './hooks'
import type { Hook, HooksView } from './types'

function HookDialog({
  view,
  initial,
  errors,
  onCancel,
  onSave,
}: {
  view: HooksView
  initial: Hook
  errors: Record<string, string>
  onCancel: () => void
  onSave: (h: Hook) => void
}) {
  const { t } = useTranslation()
  const [hook, setHook] = useState(initial)
  // keep a tab that is no longer known (stored by an older configuration) selectable
  const tabs = view.tabs.includes(hook.tab) || hook.tab === '' ? view.tabs : [hook.tab, ...view.tabs]
  const valid = hook.tab !== '' && hook.mode !== '' && hook.command.trim() !== ''
  return (
    <Dialog open onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('hooks.trigger')}</DialogTitle>
          <DialogDescription>{t('hooks.commandHelp')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="hook-tab">{t('hooks.tab')}</Label>
              <Select value={hook.tab} onValueChange={(tab) => setHook({ ...hook, tab })}>
                <SelectTrigger id="hook-tab" className="w-full" aria-invalid={!!errors.tab}>
                  <SelectValue placeholder={t('hooks.chooseTab')} />
                </SelectTrigger>
                <SelectContent>
                  {tabs.map((tab) => (
                    <SelectItem key={tab} value={tab}>
                      {tab}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {errors.tab && <p className="text-xs text-destructive">{errors.tab}</p>}
            </div>
            <div className="space-y-1">
              <Label htmlFor="hook-mode">{t('hooks.mode')}</Label>
              <Select value={hook.mode} onValueChange={(mode) => setHook({ ...hook, mode })}>
                <SelectTrigger id="hook-mode" className="w-full" aria-invalid={!!errors.mode}>
                  <SelectValue placeholder={t('hooks.chooseMode')} />
                </SelectTrigger>
                <SelectContent>
                  {view.modes.map((mode) => (
                    <SelectItem key={mode} value={mode}>
                      {t(`hooks.modes.${mode}`, { defaultValue: mode })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {errors.mode && <p className="text-xs text-destructive">{errors.mode}</p>}
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="hook-command">{t('hooks.command')}</Label>
            <Input
              id="hook-command"
              className="font-mono text-xs"
              placeholder="/usr/local/bin/provision %uid%"
              value={hook.command}
              aria-invalid={!!errors.command}
              onChange={(e) => setHook({ ...hook, command: e.target.value })}
            />
            {errors.command && <p className="text-xs text-destructive">{errors.command}</p>}
            <p className="text-caption text-muted-foreground">{t('hooks.placeholders')}</p>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="hook-enabled"
              checked={hook.enabled}
              onCheckedChange={(enabled) => setHook({ ...hook, enabled })}
            />
            <Label htmlFor="hook-enabled" className="font-normal">
              {t('hooks.enabled')}
            </Label>
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button type="button" disabled={!valid} onClick={() => onSave({ ...hook, command: hook.command.trim() })}>
            {t('common.ok')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function HooksEditor({ view }: { view: HooksView }) {
  const { t } = useTranslation()
  const save = useSaveHooks()
  const [rows, setRows] = useState<Hook[]>(view.hooks)
  const [displayOutput, setDisplayOutput] = useState(view.display_output)
  const [editing, setEditing] = useState<{ position: number; hook: Hook } | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const readOnly = !view.can_write
  const dirty =
    JSON.stringify(rows) !== JSON.stringify(view.hooks) || displayOutput !== view.display_output

  const submit = async () => {
    setErrors({})
    try {
      await save.mutateAsync({ hooks: rows, displayOutput })
      toast.success(t('hooks.saved'))
    } catch (e) {
      if (isApiError(e) && e.fields) setErrors(e.fields)
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const fieldErrors = (position: number): Record<string, string> => {
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(errors)) {
      const m = /^hooks\.(\d+)\.(\w+)$/.exec(k)
      if (m && Number(m[1]) === position && m[2]) out[m[2]] = v
    }
    return out
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Switch
            id="hooks-display-output"
            checked={displayOutput}
            disabled={readOnly}
            onCheckedChange={setDisplayOutput}
          />
          <Label htmlFor="hooks-display-output" className="font-normal">
            {t('hooks.displayOutput')}
          </Label>
        </div>
        <Button
          size="sm"
          disabled={readOnly}
          onClick={() =>
            setEditing({
              position: rows.length,
              hook: { tab: '', mode: 'postcreate', command: '', enabled: true },
            })
          }
        >
          <Plus />
          {t('hooks.add')}
        </Button>
      </div>

      {view.invalid.length > 0 && (
        <div role="status" className="rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-body">
          <p className="flex items-center gap-1.5 font-medium text-warning">
            <TriangleAlert className="size-3.5" aria-hidden />
            {t('hooks.invalid')}
          </p>
          <ul className="mt-1 font-mono text-caption text-muted-foreground">
            {view.invalid.map((raw) => (
              <li key={raw} className="break-all">
                {raw}
              </li>
            ))}
          </ul>
        </div>
      )}

      {rows.length === 0 ? (
        <EmptyState icon={<Workflow />} title={t('hooks.none')} description={t('hooks.noneHelp')} />
      ) : (
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('hooks.tab')}</TableHead>
                <TableHead>{t('hooks.mode')}</TableHead>
                <TableHead>{t('hooks.status')}</TableHead>
                <TableHead>{t('hooks.command')}</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((h, i) => (
                <TableRow key={`${h.tab}|${h.mode}|${i}`}>
                  <TableCell className="font-mono text-xs">{h.tab}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{t(`hooks.modes.${h.mode}`, { defaultValue: h.mode })}</Badge>
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={h.enabled}
                      disabled={readOnly}
                      aria-label={t('hooks.toggle', { tab: h.tab, mode: h.mode })}
                      onCheckedChange={(enabled) =>
                        setRows(rows.map((x, j) => (j === i ? { ...x, enabled } : x)))
                      }
                    />
                  </TableCell>
                  <TableCell className="max-w-md truncate font-mono text-xs text-muted-foreground" title={h.command}>
                    {h.command}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      disabled={readOnly}
                      aria-label={t('hooks.edit', { tab: h.tab, mode: h.mode })}
                      onClick={() => setEditing({ position: i, hook: h })}
                    >
                      <Pencil />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      disabled={readOnly}
                      aria-label={t('hooks.delete', { tab: h.tab, mode: h.mode })}
                      onClick={() => setRows(rows.filter((_, j) => j !== i))}
                    >
                      <Trash2 />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {Object.keys(errors).length > 0 && editing === null && (
        <ul role="alert" className="text-xs text-destructive">
          {Object.entries(errors).map(([k, v]) => (
            <li key={k}>
              {k}: {v}
            </li>
          ))}
        </ul>
      )}

      <div className="sticky bottom-0 flex items-center justify-end gap-2 border-t bg-background/95 py-3 backdrop-blur">
        <p className="mr-auto text-body text-muted-foreground" aria-live="polite">
          {readOnly ? t('config.readOnly') : dirty ? t('hooks.unsaved') : t('config.noChanges')}
        </p>
        <Button
          variant="outline"
          size="sm"
          disabled={!dirty || save.isPending}
          onClick={() => {
            setRows(view.hooks)
            setDisplayOutput(view.display_output)
            setErrors({})
          }}
        >
          <Undo2 />
          {t('config.discard')}
        </Button>
        <Button size="sm" disabled={readOnly || !dirty || save.isPending} onClick={() => void submit()}>
          <Save />
          {t('common.save')}
        </Button>
      </div>

      {editing && (
        <HookDialog
          key={editing.position}
          view={view}
          initial={editing.hook}
          errors={fieldErrors(editing.position)}
          onCancel={() => setEditing(null)}
          onSave={(h) => {
            setRows(
              editing.position >= rows.length
                ? [...rows, h]
                : rows.map((x, j) => (j === editing.position ? h : x)),
            )
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}

export function HooksSection() {
  const { data, isPending, isError, error, refetch } = useHooks()
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />
  if (isPending) return <Skeleton className="h-40 w-full" />
  return <HooksEditor key={JSON.stringify(data.hooks) + String(data.display_output)} view={data} />
}

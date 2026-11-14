import { Pencil, Plus, Save, TriangleAlert, Trash2, Undo2 } from 'lucide-react'
import { useMemo, useState } from 'react'
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
import { checkHook, checkHooks, type HookErrors, type HookField } from './hookRules'
import type { Hook, HooksView } from './types'

type Touched = Partial<Record<HookField, boolean>>

function HookDialog({
  view,
  tabs,
  initial,
  others,
  errors,
  onCancel,
  onSave,
}: {
  view: HooksView
  /** Tabs the server accepts, plus the ones already stored. */
  tabs: readonly string[]
  initial: Hook
  /** The other triggers: this one must differ from all of them. */
  others: readonly Hook[]
  /** Errors the server returned for this trigger, by field. */
  errors: HookErrors
  onCancel: () => void
  onSave: (h: Hook) => void
}) {
  const { t } = useTranslation()
  const [hook, setHook] = useState(initial)
  const [touched, setTouched] = useState<Touched>({})
  const [attempted, setAttempted] = useState(false)
  const choices = tabs.includes(hook.tab) || hook.tab === '' ? tabs : [hook.tab, ...tabs]
  const problems = checkHook(hook, others, tabs, view.modes)
  const count = Object.keys(problems).length
  const touch = (field: HookField) => setTouched((s) => ({ ...s, [field]: true }))
  // a server error stays until the user changes the field it is about
  const shown = (field: HookField): string | undefined =>
    (touched[field] || attempted ? problems[field] : undefined) ??
    (hook[field] === initial[field] ? errors[field] : undefined)
  const tabError = shown('tab')
  const modeError = shown('mode')
  const commandError = shown('command')
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
              <Select
                value={hook.tab}
                onValueChange={(tab) => {
                  setHook({ ...hook, tab })
                  touch('tab')
                }}
                onOpenChange={(open) => !open && touch('tab')}
              >
                <SelectTrigger
                  id="hook-tab"
                  className="w-full"
                  aria-invalid={!!tabError}
                  aria-describedby={tabError ? 'hook-tab-error' : undefined}
                >
                  <SelectValue placeholder={t('hooks.chooseTab')} />
                </SelectTrigger>
                <SelectContent>
                  {choices.map((tab) => (
                    <SelectItem key={tab} value={tab}>
                      {tab}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {tabError && (
                <p id="hook-tab-error" role="alert" className="text-xs text-destructive">
                  {tabError}
                </p>
              )}
            </div>
            <div className="space-y-1">
              <Label htmlFor="hook-mode">{t('hooks.mode')}</Label>
              <Select
                value={hook.mode}
                onValueChange={(mode) => {
                  setHook({ ...hook, mode })
                  touch('mode')
                }}
                onOpenChange={(open) => !open && touch('mode')}
              >
                <SelectTrigger
                  id="hook-mode"
                  className="w-full"
                  aria-invalid={!!modeError}
                  aria-describedby={modeError ? 'hook-mode-error' : undefined}
                >
                  <SelectValue placeholder={t('hooks.chooseMode')} />
                </SelectTrigger>
                <SelectContent>
                  {view.modes.map((mode) => (
                    <SelectItem key={mode} value={mode}>
                      {t(`hooks.modes.${mode}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {modeError && (
                <p id="hook-mode-error" role="alert" className="text-xs text-destructive">
                  {modeError}
                </p>
              )}
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="hook-command">{t('hooks.command')}</Label>
            <Input
              id="hook-command"
              className="font-mono text-xs"
              placeholder="/usr/local/bin/provision %uid%"
              value={hook.command}
              aria-invalid={!!commandError}
              aria-describedby={commandError ? 'hook-command-error' : undefined}
              onBlur={() => touch('command')}
              onChange={(e) => setHook({ ...hook, command: e.target.value })}
            />
            {commandError && (
              <p id="hook-command-error" role="alert" className="text-xs text-destructive">
                {commandError}
              </p>
            )}
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
        <DialogFooter className="items-center">
          {attempted && count > 0 && (
            <p role="alert" className="mr-auto text-small text-destructive">
              {t('hooks.errors.dialogBlocked', { count })}
            </p>
          )}
          <Button type="button" variant="outline" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button
            type="button"
            onClick={() => {
              if (count > 0) setAttempted(true)
              else onSave({ ...hook, tab: hook.tab.trim(), command: hook.command.trim() })
            }}
          >
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
  const [rows, setRowsRaw] = useState<Hook[]>(view.hooks)
  const [displayOutput, setDisplayOutput] = useState(view.display_output)
  const [editing, setEditing] = useState<{ position: number; hook: Hook } | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const readOnly = !view.can_write
  const dirty =
    JSON.stringify(rows) !== JSON.stringify(view.hooks) || displayOutput !== view.display_output
  // a tab already stored stays valid even when the server no longer lists it
  const knownTabs = useMemo(
    () => [...new Set([...view.tabs, ...view.hooks.map((h) => h.tab)])],
    [view.tabs, view.hooks],
  )
  const clientErrors = checkHooks(rows, knownTabs, view.modes)
  const invalidRows = Object.keys(clientErrors).length

  // editing the list makes the server's answer about the previous list obsolete
  const setRows = (next: Hook[]) => {
    setRowsRaw(next)
    setErrors({})
  }

  const submit = async () => {
    setErrors({})
    try {
      await save.mutateAsync({ hooks: rows, displayOutput })
      toast.success(t('hooks.saved'))
    } catch (e) {
      if (isApiError(e) && Object.keys(e.fields).length > 0) setErrors(e.fields)
      else toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const fieldErrors = (position: number): HookErrors => {
    const out: HookErrors = {}
    for (const [k, v] of Object.entries(errors)) {
      const m = /^hooks\.(\d+)\.(tab|mode|command)$/.exec(k)
      if (m && Number(m[1]) === position) out[m[2] as HookField] = v
    }
    return out
  }

  /** What is wrong with a row: the browser's own check, else what the server said. */
  const rowError = (position: number): string | undefined => {
    const found = { ...fieldErrors(position), ...clientErrors[position] }
    return found.command ?? found.tab ?? found.mode
  }

  // server errors that name no trigger field (they would otherwise never be seen)
  const generalErrors = Object.entries(errors).filter(([k]) => !/^hooks\.\d+\.(tab|mode|command)$/.test(k))

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
                    <Badge variant="outline">{t(`hooks.modes.${h.mode}`)}</Badge>
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
                  <TableCell className="max-w-md font-mono text-xs text-muted-foreground">
                    <div className="truncate" title={h.command}>
                      {h.command}
                    </div>
                    {rowError(i) && (
                      <p role="alert" className="mt-0.5 font-sans text-destructive">
                        {rowError(i)}
                      </p>
                    )}
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

      {generalErrors.length > 0 && editing === null && (
        <ul role="alert" className="text-xs text-destructive">
          {generalErrors.map(([k, v]) => (
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
        {invalidRows > 0 && (
          <p role="alert" className="text-small text-destructive">
            {t('hooks.errors.blocked', { count: invalidRows })}
          </p>
        )}
        <Button
          variant="outline"
          size="sm"
          disabled={!dirty || save.isPending}
          onClick={() => {
            setRows(view.hooks)
            setDisplayOutput(view.display_output)
          }}
        >
          <Undo2 />
          {t('config.discard')}
        </Button>
        <Button
          size="sm"
          disabled={readOnly || !dirty || save.isPending || invalidRows > 0}
          onClick={() => void submit()}
        >
          <Save />
          {t('common.save')}
        </Button>
      </div>

      {editing && (
        <HookDialog
          key={editing.position}
          view={view}
          tabs={knownTabs}
          initial={editing.hook}
          others={rows.filter((_, j) => j !== editing.position)}
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

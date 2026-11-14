import { AlertTriangle, Save, Undo2 } from 'lucide-react'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { useWritesAllowed } from '@/components/resilience'
import type { FieldDiff } from '@/lib/objects'
import { ReviewChangesPopover } from './ReviewChangesPopover'

/** A tab holding fields the client validation refuses, with how many. */
export interface InvalidTab {
  name: string
  label: string
  count: number
}

interface Props {
  dirty: boolean
  isSubmitting: boolean
  isCreate: boolean
  changesCount: number
  diffs: FieldDiff[]
  /** Fields the client validation refuses right now (saving is blocked while > 0). */
  invalidCount?: number
  invalidTabs?: InvalidTab[]
  /** Reveal the errors of `tab` inline and move the cursor to the first one. */
  onShowErrors?: (tab: string) => void
  onDiscard: () => void
  onSave: () => void
}

export function EditorSaveBar({
  dirty,
  isSubmitting,
  isCreate,
  changesCount,
  diffs,
  invalidCount = 0,
  invalidTabs = [],
  onShowErrors,
  onDiscard,
  onSave,
}: Props) {
  const { t } = useTranslation()
  const writesAllowed = useWritesAllowed()
  const blocked = invalidCount > 0

  // Global ⌘S / Ctrl+S shortcut to save changes
  useEffect(() => {
    if (!dirty) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        onSave()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [dirty, onSave])

  if (!dirty) return null

  return (
    <aside
      aria-label={t('editor.unsaved')}
      className="sticky bottom-0 z-30 -mx-4 mt-auto -mb-4 flex min-h-14 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t bg-card px-6 py-2 md:-mx-6 md:-mb-5"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
        <div className="flex items-center gap-2">
          <span className="size-1.5 rounded-full bg-signal" />
          <span
            data-testid="dirty-indicator"
            className="text-body font-medium text-foreground"
          >
            {t('editor.unsavedCount', {
              count: changesCount || diffs.length || 1,
              defaultValue: t('editor.unsaved'),
            })}
          </span>
        </div>
        {blocked && (
          <div
            role="status"
            data-testid="invalid-summary"
            className="flex flex-wrap items-center gap-x-2 gap-y-1 text-body text-destructive"
          >
            <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
            <span className="font-medium">{t('editorValidation.summary', { count: invalidCount })}</span>
            <span className="text-muted-foreground">{t('editorValidation.inTabs')}</span>
            {invalidTabs.map((tab) => (
              <button
                key={tab.name}
                type="button"
                onClick={() => onShowErrors?.(tab.name)}
                className="rounded-sm underline underline-offset-2 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                {tab.label} ({tab.count})
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        {diffs.length > 0 && <ReviewChangesPopover diffs={diffs} />}

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onDiscard}
          disabled={isSubmitting}
        >
          <Undo2 aria-hidden />
          {t('editor.discard')}
        </Button>

        <Button
          type="submit"
          size="sm"
          disabled={isSubmitting || !writesAllowed}
          aria-disabled={blocked || undefined}
          title={blocked ? t('editorValidation.saveBlocked') : t('editor.saveShortcut')}
          className={blocked ? 'opacity-60' : undefined}
        >
          <Save aria-hidden />
          <span>{isCreate ? t('common.create') : t('common.save')}</span>
          <kbd className="ml-1 hidden rounded-sm border border-primary-foreground/30 px-1 py-0.5 font-mono text-micro leading-none sm:inline-block">
            ⌘S
          </kbd>
        </Button>
      </div>
    </aside>
  )
}

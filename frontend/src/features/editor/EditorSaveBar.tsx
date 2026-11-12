import { Save, Undo2 } from 'lucide-react'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { useWritesAllowed } from '@/components/resilience'
import type { FieldDiff } from '@/lib/objects'
import { ReviewChangesPopover } from './ReviewChangesPopover'

interface Props {
  dirty: boolean
  isSubmitting: boolean
  isCreate: boolean
  changesCount: number
  diffs: FieldDiff[]
  onDiscard: () => void
  onSave: () => void
}

export function EditorSaveBar({
  dirty,
  isSubmitting,
  isCreate,
  changesCount,
  diffs,
  onDiscard,
  onSave,
}: Props) {
  const { t } = useTranslation()
  const writesAllowed = useWritesAllowed()

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
      className="sticky bottom-0 z-30 -mx-4 mt-auto -mb-4 flex h-14 items-center justify-between gap-3 border-t bg-card px-6 md:-mx-6 md:-mb-5"
    >
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
          title={t('editor.saveShortcut')}
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

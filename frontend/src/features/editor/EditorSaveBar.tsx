import { Save, Undo2 } from 'lucide-react'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
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
      className="sticky bottom-4 z-30 mx-auto w-full max-w-5xl rounded-lg border border-border bg-card/95 p-3 shadow-lg backdrop-blur-md transition-all animate-in fade-in slide-in-from-bottom-2"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="bg-primary size-2 rounded-full animate-pulse" />
          <span
            data-testid="dirty-indicator"
            className="text-xs font-medium text-foreground"
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
            variant="ghost"
            size="sm"
            onClick={onDiscard}
            disabled={isSubmitting}
            className="h-8 gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <Undo2 className="size-3.5" />
            {t('editor.discard')}
          </Button>

          <Button
            type="submit"
            size="sm"
            disabled={isSubmitting}
            className="h-8 gap-1.5 text-xs font-medium"
            title={t('editor.saveShortcut')}
          >
            <Save className="size-3.5" />
            <span>{isCreate ? t('common.create') : t('common.save')}</span>
            <kbd className="ml-1 hidden sm:inline-block rounded border border-primary-foreground/30 px-1 py-0.5 text-[10px] font-mono leading-none">
              ⌘S
            </kbd>
          </Button>
        </div>
      </div>
    </aside>
  )
}

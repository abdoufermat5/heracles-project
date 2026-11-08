import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { TabDescriptor } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

interface Props {
  tabs: TabDescriptor[]
  currentTab: string
  onSelectTab: (tabName: string) => void
  active: Record<string, boolean>
  errorsByTab: Record<string, number>
  dirtyTabs: Set<string>
  /** Extra panels listed after the object tabs (references, snapshots, ...). */
  extras?: Array<{ name: string; label: string }>
}

export function EditorTabNav({
  tabs,
  currentTab,
  onSelectTab,
  active,
  errorsByTab,
  dirtyTabs,
  extras = [],
}: Props) {
  const { t } = useTranslation()

  return (
    <nav aria-label="Object tabs" className="w-full lg:w-56 lg:shrink-0">
      <div
        role="tablist"
        aria-label={t('editor.tabs', 'Tabs')}
        className="flex gap-1 overflow-x-auto border-b lg:flex-col lg:overflow-visible lg:border-b-0"
      >
        {tabs.map((tb) => {
          const isSelected = currentTab === tb.name
          const isActive = active[tb.name] ?? false
          const isOptional = tb.optional
          const errorCount = errorsByTab[tb.name] ?? 0
          const isDirty = dirtyTabs.has(tb.name)

          return (
            <button
              key={tb.name}
              type="button"
              role="tab"
              aria-selected={isSelected}
              aria-controls={`panel-${tb.name}`}
              id={`tab-${tb.name}`}
              onClick={() => onSelectTab(tb.name)}
              className={cn(
                'group relative flex h-8 items-center justify-between gap-2 whitespace-nowrap rounded-sm border border-transparent px-3 text-left text-[13px] transition-colors lg:whitespace-normal',
                isSelected
                  ? 'border-border bg-card font-medium text-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                isOptional && !isActive && !isSelected && 'text-muted-foreground/70',
              )}
            >
              {isSelected && (
                <span
                  className="absolute inset-y-0 left-0 w-0.5 bg-signal"
                  aria-hidden
                />
              )}

              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate">{tb.label}</span>
                {isOptional && !isActive && (
                  <Badge
                    variant="neutral"
                    className="h-4 shrink-0 rounded-sm px-1 text-[10px] font-normal"
                  >
                    {t('editor.inactive')}
                  </Badge>
                )}
              </div>

              <div className="ml-2 flex shrink-0 items-center gap-1.5">
                {isDirty && !errorCount && (
                  <span
                    className="size-1.5 rounded-full bg-signal"
                    title={t('editor.unsaved')}
                  />
                )}
                {errorCount > 0 && (
                  <Badge
                    variant="destructive"
                    className="flex h-4 min-w-4 items-center gap-0.5 rounded-sm px-1 text-[10px] leading-none"
                    aria-label={t('editor.tabHasErrors')}
                  >
                    <AlertTriangle className="size-2.5" />
                    <span>{errorCount}</span>
                  </Badge>
                )}
              </div>
            </button>
          )
        })}
        {extras.map((x) => {
          const isSelected = currentTab === x.name
          return (
            <button
              key={x.name}
              type="button"
              role="tab"
              aria-selected={isSelected}
              aria-controls={`panel-${x.name}`}
              id={`tab-${x.name}`}
              onClick={() => onSelectTab(x.name)}
              className={cn(
                'relative flex h-8 items-center gap-2 whitespace-nowrap rounded-sm border border-transparent px-3 text-left text-[13px] transition-colors',
                isSelected
                  ? 'border-border bg-card font-medium text-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              {isSelected && <span className="absolute inset-y-0 left-0 w-0.5 bg-signal" aria-hidden />}
              <span className="truncate">{x.label}</span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}

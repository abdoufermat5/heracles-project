import { AlertTriangle, CheckCircle2, CircleDot } from 'lucide-react'
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
}

export function EditorTabNav({
  tabs,
  currentTab,
  onSelectTab,
  active,
  errorsByTab,
  dirtyTabs,
}: Props) {
  const { t } = useTranslation()

  return (
    <nav aria-label="Object tabs" className="w-full lg:w-56 lg:shrink-0">
      <div
        role="tablist"
        aria-label={t('editor.tabs', 'Tabs')}
        className="flex lg:flex-col overflow-x-auto lg:overflow-visible border-b lg:border-b-0 border-border pb-1 lg:pb-0 gap-1"
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
                'group flex items-center justify-between whitespace-nowrap lg:whitespace-normal rounded-md lg:rounded-lg px-3 py-1.5 lg:py-2 text-left text-xs font-medium transition-colors',
                isSelected
                  ? 'bg-primary-soft text-primary font-semibold shadow-xs'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              <div className="flex min-w-0 items-center gap-2">
                {isOptional ? (
                  isActive ? (
                    <CheckCircle2 className="size-3.5 text-success shrink-0" />
                  ) : (
                    <CircleDot className="size-3.5 text-muted-foreground shrink-0 opacity-50" />
                  )
                ) : null}
                <span className="truncate">{tb.label}</span>
                {isOptional && !isActive && (
                  <span className="text-muted-foreground text-[10px] font-normal shrink-0">
                    ({t('editor.inactive')})
                  </span>
                )}
              </div>

              <div className="flex items-center gap-1.5 shrink-0 ml-2">
                {isDirty && !errorCount && (
                  <span
                    className="bg-primary size-1.5 lg:size-2 rounded-full"
                    title={t('editor.unsaved')}
                  />
                )}
                {errorCount > 0 && (
                  <Badge
                    variant="destructive"
                    className="h-4 min-w-4 px-1 text-[10px] leading-none flex items-center gap-0.5"
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
      </div>
    </nav>
  )
}

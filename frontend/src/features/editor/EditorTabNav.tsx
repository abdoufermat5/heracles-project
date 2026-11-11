import { AlertTriangle, Plus, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { TabDescriptor } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
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
  /** Optional tabs activated during this edit session and not saved yet. */
  newTabs?: Set<string>
  /** Whether the user may enable/disable capabilities right now. */
  canChangeCapabilities?: boolean
  onSetTabActive?: (tabName: string, value: boolean) => void
}

export function EditorTabNav({
  tabs,
  currentTab,
  onSelectTab,
  active,
  errorsByTab,
  dirtyTabs,
  extras = [],
  newTabs = new Set<string>(),
  canChangeCapabilities = false,
  onSetTabActive,
}: Props) {
  const { t } = useTranslation()

  // Main tab, active tabs, and the selected tab (even if inactive, so it stays visible).
  const shown = tabs.filter((tb) => !tb.optional || (active[tb.name] ?? false) || currentTab === tb.name)
  const available = tabs.filter((tb) => tb.optional && !(active[tb.name] ?? false))

  return (
    <nav aria-label="Object tabs" className="w-full lg:w-56 lg:shrink-0">
      <div
        role="tablist"
        aria-label={t('editor.tabs', 'Tabs')}
        className="flex gap-1 overflow-x-auto border-b lg:flex-col lg:overflow-visible lg:border-b-0"
      >
        {shown.map((tb) => {
          const isSelected = currentTab === tb.name
          const isActive = active[tb.name] ?? false
          const isOptional = tb.optional
          const errorCount = errorsByTab[tb.name] ?? 0
          const isDirty = dirtyTabs.has(tb.name)

          const isNew = newTabs.has(tb.name)

          return (
            <div key={tb.name} role="presentation" className="flex items-center gap-1">
            <button
              type="button"
              role="tab"
              aria-selected={isSelected}
              aria-controls={`panel-${tb.name}`}
              id={`tab-${tb.name}`}
              onClick={() => onSelectTab(tb.name)}
              className={cn(
                'group relative flex h-8 min-w-0 flex-1 items-center justify-between gap-2 whitespace-nowrap rounded-sm border border-transparent px-3 text-left text-body transition-colors lg:whitespace-normal',
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
                {isNew && (
                  <Badge
                    variant="neutral"
                    className="h-4 shrink-0 rounded-sm px-1 text-micro font-normal"
                  >
                    {t('editor.newCapability', 'new')}
                  </Badge>
                )}
                {isOptional && !isActive && (
                  <Badge
                    variant="neutral"
                    className="h-4 shrink-0 rounded-sm px-1 text-micro font-normal"
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
                    className="flex h-4 min-w-4 items-center gap-0.5 rounded-sm px-1 text-micro leading-none"
                    aria-label={t('editor.tabHasErrors')}
                  >
                    <AlertTriangle className="size-2.5" />
                    <span>{errorCount}</span>
                  </Badge>
                )}
              </div>
            </button>
            {isNew && canChangeCapabilities && (
              <button
                type="button"
                aria-label={t('editor.removeCapability', { tab: tb.label })}
                title={t('editor.removeCapability', { tab: tb.label })}
                onClick={() => onSetTabActive?.(tb.name, false)}
                className="flex size-6 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            )}
            </div>
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
                'relative flex h-8 items-center gap-2 whitespace-nowrap rounded-sm border border-transparent px-3 text-left text-body transition-colors',
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
      {available.length > 0 && (
        <div className="mt-2 border-t pt-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-full justify-start"
                disabled={!canChangeCapabilities}
                title={canChangeCapabilities ? undefined : t('editor.addCapabilityHint')}
              >
                <Plus className="size-3.5" />
                {t('editor.addCapability')}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-72">
              <DropdownMenuLabel>{t('editor.availableCapabilities')}</DropdownMenuLabel>
              {available.map((tb) => (
                <DropdownMenuItem
                  key={tb.name}
                  onSelect={() => {
                    onSetTabActive?.(tb.name, true)
                    onSelectTab(tb.name)
                  }}
                  className="flex-col items-start gap-0.5"
                >
                  <span className="font-medium">{tb.label}</span>
                  {tb.description && (
                    <span className="text-caption text-muted-foreground">{tb.description}</span>
                  )}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}
    </nav>
  )
}

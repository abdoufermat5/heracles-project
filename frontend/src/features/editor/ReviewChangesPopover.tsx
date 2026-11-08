import { Eye } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { FieldDiff } from '@/lib/objects'

interface Props {
  diffs: FieldDiff[]
}

function formatVal(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (Array.isArray(v)) return v.length === 0 ? '—' : v.join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

export function ReviewChangesPopover({ diffs }: Props) {
  const { t } = useTranslation()

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 gap-1.5 text-xs font-normal"
        >
          <Eye className="size-3.5" />
          {t('editor.reviewChanges')}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 sm:w-96 p-0 shadow-lg" align="end">
        <div className="border-b border-border px-3.5 py-2.5">
          <p className="text-xs font-semibold text-foreground">
            {t('editor.reviewChanges')} ({diffs.length})
          </p>
        </div>
        <ScrollArea className="max-h-72 p-3">
          {diffs.length === 0 ? (
            <p className="text-muted-foreground p-3 text-center text-xs">
              {t('editor.noChanges')}
            </p>
          ) : (
            <div className="space-y-3">
              {diffs.map((d) => (
                <div
                  key={`${d.tab}.${d.attr}`}
                  className="rounded-md border border-border bg-muted/20 p-2.5 text-xs space-y-1.5"
                >
                  <div className="flex items-center justify-between font-medium">
                    <span className="text-foreground">{d.attrLabel}</span>
                    <span className="text-muted-foreground text-[10px] uppercase tracking-wider font-mono">
                      {d.tabLabel}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 pt-1 border-t border-border/50">
                    <div>
                      <span className="text-muted-foreground text-[10px] uppercase tracking-wide block mb-0.5">
                        {t('editor.changeOld')}
                      </span>
                      <span className="text-destructive font-mono truncate block line-through opacity-80">
                        {formatVal(d.oldValue)}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground text-[10px] uppercase tracking-wide block mb-0.5">
                        {t('editor.changeNew')}
                      </span>
                      <span className="text-success font-mono truncate block font-medium">
                        {formatVal(d.newValue)}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  )
}

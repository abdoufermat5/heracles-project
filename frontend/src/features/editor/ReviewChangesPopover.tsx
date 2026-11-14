import { Eye } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import { attributeLabel } from '@/lib/labels'
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
        <Button type="button" variant="ghost" size="sm">
          <Eye aria-hidden />
          {t('editor.reviewChanges')}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0 sm:w-96" align="end">
        <div className="flex h-10 items-center border-b px-4">
          <p className="text-body font-semibold text-foreground">
            {t('editor.reviewChanges')} ({diffs.length})
          </p>
        </div>
        <ScrollArea className="max-h-72">
          {diffs.length === 0 ? (
            <p className="p-4 text-center text-body text-muted-foreground">
              {t('editor.noChanges')}
            </p>
          ) : (
            <ul className="divide-y">
              {diffs.map((d) => (
                <li key={`${d.tab}.${d.attr}`} className="space-y-2 px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-body font-medium text-foreground">
                      {attributeLabel(t, d.attr, d.attrLabel)}
                    </span>
                    <span className="font-mono text-caption text-muted-foreground">
                      {d.tabLabel}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <span className="label-caps block">{t('editor.changeOld')}</span>
                      <span className="mt-0.5 block truncate font-mono text-xs text-destructive line-through">
                        {formatVal(d.oldValue)}
                      </span>
                    </div>
                    <div>
                      <span className="label-caps block">{t('editor.changeNew')}</span>
                      <span className="mt-0.5 block truncate font-mono text-xs font-medium text-success">
                        {formatVal(d.newValue)}
                      </span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </ScrollArea>
      </PopoverContent>
    </Popover>
  )
}

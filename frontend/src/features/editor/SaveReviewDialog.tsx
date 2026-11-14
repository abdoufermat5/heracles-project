import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { FieldDiff } from '@/lib/objects'
import { attributeLabel } from '@/lib/labels'

function formatVal(v: unknown, empty: string): string {
  if (v === null || v === undefined || v === '') return empty
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (Array.isArray(v)) return v.length === 0 ? empty : v.join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/** A password is never echoed back, only the fact that it changes. */
const SECRET = /password|secret/i

interface Props {
  open: boolean
  /** What is being changed (DN or name), shown in the description. */
  target: string
  diffs: FieldDiff[]
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Confirmation step of every edit: lists each attribute with its technical name, the old
 * and the new value. The save only runs when the person confirms here.
 */
export function SaveReviewDialog({ open, target, diffs, busy = false, onConfirm, onCancel }: Props) {
  const { t } = useTranslation()
  const empty = t('safety.emptyValue')
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('safety.reviewTitle')}</DialogTitle>
          <DialogDescription>
            {t('safety.reviewDescription', { count: diffs.length, target })}
          </DialogDescription>
        </DialogHeader>
        <ul className="max-h-80 divide-y overflow-auto rounded-md border" data-testid="review-diffs">
          {diffs.map((d) => {
            const secret = SECRET.test(d.attr)
            return (
              <li key={`${d.tab}.${d.attr}`} className="space-y-1.5 px-3 py-2.5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-body font-medium">{attributeLabel(t, d.attr, d.attrLabel)}</span>
                  <span className="font-mono text-caption text-muted-foreground">{d.attr}</span>
                </div>
                <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-2 font-mono text-xs">
                  <span className="break-all text-destructive line-through">
                    {secret ? '••••••' : formatVal(d.oldValue, empty)}
                  </span>
                  <span aria-hidden className="text-muted-foreground">
                    →
                  </span>
                  <span className="break-all font-medium text-success">
                    {secret ? '••••••' : formatVal(d.newValue, empty)}
                  </span>
                </div>
              </li>
            )
          })}
        </ul>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
            {t('safety.cancel')}
          </Button>
          <Button type="button" onClick={onConfirm} disabled={busy}>
            {t('safety.confirmSave')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

import { Loader2, Pencil } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/**
 * A titled block of a page. With `editable`, it carries its own Edit / Save /
 * Cancel so people change one section at a time instead of the whole page.
 */
export function SectionCard({
  id,
  title,
  description,
  actions,
  editable = false,
  editing = false,
  saving = false,
  canSave = true,
  onEdit,
  onSave,
  onCancel,
  footer,
  children,
  className,
  bodyClassName,
}: {
  id?: string
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  editable?: boolean
  editing?: boolean
  saving?: boolean
  canSave?: boolean
  onEdit?: () => void
  onSave?: () => void
  onCancel?: () => void
  footer?: React.ReactNode
  children: React.ReactNode
  className?: string
  bodyClassName?: string
}) {
  const { t } = useTranslation()
  return (
    <section
      id={id}
      data-slot="section-card"
      data-editing={editing || undefined}
      className={cn(
        'rounded-lg border bg-card text-card-foreground transition-shadow',
        editing && 'ring-2 ring-ring/20',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3 border-b px-5 py-3.5">
        <div className="min-w-0">
          <h2 className="text-body font-semibold text-foreground">{title}</h2>
          {description && <p className="mt-0.5 text-small text-muted-foreground">{description}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          {editable && !editing && (
            <Button type="button" variant="ghost" size="sm" onClick={onEdit}>
              <Pencil aria-hidden />
              {t('patterns.edit')}
            </Button>
          )}
        </div>
      </div>
      <div className={cn('px-5 py-4', bodyClassName)}>{children}</div>
      {editing && (
        <div className="flex items-center justify-end gap-2 border-t bg-muted/40 px-5 py-3">
          <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={saving}>
            {t('patterns.cancel')}
          </Button>
          <Button type="button" size="sm" onClick={onSave} disabled={saving || !canSave}>
            {saving && <Loader2 className="animate-spin" aria-hidden />}
            {t('patterns.save')}
          </Button>
        </div>
      )}
      {!editing && footer && <div className="border-t px-5 py-3">{footer}</div>}
    </section>
  )
}

/** Label / value pairs for read views ("Department · Paris › Sales"). */
export function FactList({
  items,
  columns = 2,
  className,
}: {
  items: { label: React.ReactNode; value: React.ReactNode }[]
  columns?: 1 | 2 | 3
  className?: string
}) {
  const { t } = useTranslation()
  return (
    <dl
      className={cn(
        'grid gap-x-8 gap-y-4',
        columns === 2 && 'sm:grid-cols-2',
        columns === 3 && 'sm:grid-cols-2 lg:grid-cols-3',
        className,
      )}
    >
      {items.map((item, i) => (
        <div key={i} className="min-w-0 space-y-1">
          <dt className="text-small text-muted-foreground">{item.label}</dt>
          <dd className="text-body break-words text-foreground">
            {item.value === null || item.value === undefined || item.value === '' ? (
              <span className="text-muted-foreground">{t('patterns.notSet')}</span>
            ) : (
              item.value
            )}
          </dd>
        </div>
      ))}
    </dl>
  )
}

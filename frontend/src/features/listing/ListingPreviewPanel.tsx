import { Link } from '@tanstack/react-router'
import {
  Check,
  Copy,
  ExternalLink,
  Lock,
  LockOpen,
  Trash2,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ObjectListItem, TypeDescriptor, TypeSummary } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { TypeIcon } from '@/lib/icons'
import { formatCellValue, getInitials, isMonospaceKey } from './types'

interface ListingPreviewPanelProps {
  type: string
  item: ObjectListItem | null
  descriptor?: TypeDescriptor
  summary?: TypeSummary
  onClose: () => void
  onCopyDn: (dn: string) => void
  onLockToggle?: (dn: string, lock: boolean) => void
  onDeleteSingle?: (item: ObjectListItem) => void
}

export function ListingPreviewPanel({
  type,
  item,
  descriptor,
  summary,
  onClose,
  onCopyDn,
  onLockToggle,
  onDeleteSingle,
}: ListingPreviewPanelProps) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  if (!item) {
    return (
      <aside
        aria-label={t('listing.preview')}
        className="bg-card border-border flex w-80 shrink-0 flex-col items-center justify-center rounded-xl border p-6 text-center shadow-xs"
      >
        <p className="text-muted-foreground text-xs">{t('listing.itemDetails')}</p>
      </aside>
    )
  }

  const nameAttr = descriptor?.name_attr ?? descriptor?.main_attr ?? 'cn'
  const title = String(item.values[nameAttr] ?? item.values[descriptor?.main_attr ?? ''] ?? item.dn)
  const isPerson = type === 'user'

  const handleCopy = () => {
    onCopyDn(item.dn)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <aside
      aria-label={t('listing.preview')}
      className="bg-card border-border flex w-84 shrink-0 flex-col overflow-hidden rounded-xl border shadow-xs animate-in fade-in-0 slide-in-from-right-3 duration-200"
    >
      {/* Panel Header */}
      <div className="border-b border-border/80 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5 min-w-0">
            {isPerson ? (
              <div className="bg-primary/10 text-primary flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold">
                {getInitials(title)}
              </div>
            ) : (
              <div className="bg-muted text-foreground flex size-9 shrink-0 items-center justify-center rounded-lg">
                <TypeIcon name={summary?.icon ?? descriptor?.icon ?? type} className="size-4" />
              </div>
            )}
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-sm font-semibold tracking-tight" title={title}>
                {title}
              </h2>
              <div className="flex items-center gap-1.5 mt-0.5">
                {item.locked ? (
                  <Badge variant="outline" className="text-warning border-warning/40 h-4 px-1.5 text-[10px] gap-1">
                    <Lock className="size-2.5" aria-hidden />
                    {t('listing.locked')}
                  </Badge>
                ) : (
                  <Badge variant="outline" className="text-success border-success/40 h-4 px-1.5 text-[10px]">
                    {t('listing.filterActive')}
                  </Badge>
                )}
              </div>
            </div>
          </div>

          <Button
            variant="ghost"
            size="sm"
            className="size-7 p-0 text-muted-foreground hover:text-foreground"
            onClick={onClose}
            aria-label={t('listing.closePreview')}
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>

        {/* DN badge + copy button */}
        <div className="bg-muted/60 border-border mt-3 flex items-center justify-between rounded-md border px-2.5 py-1.5 text-xs">
          <span className="truncate font-mono text-[11px] text-muted-foreground" title={item.dn}>
            {item.dn}
          </span>
          <button
            type="button"
            onClick={handleCopy}
            className="text-muted-foreground hover:text-foreground ml-1.5 inline-flex shrink-0 items-center transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            aria-label={t('listing.copyDn')}
            title={t('listing.copyDn')}
          >
            {copied ? (
              <Check className="size-3.5 text-success" aria-hidden />
            ) : (
              <Copy className="size-3.5" aria-hidden />
            )}
          </button>
        </div>
      </div>

      {/* Main Action */}
      <div className="p-4 border-b border-border/80">
        <Button asChild size="sm" className="w-full h-8 gap-1.5 text-xs shadow-xs">
          <Link to="/types/$type/$dn" params={{ type, dn: item.dn }}>
            <ExternalLink className="size-3.5" aria-hidden />
            {t('listing.open')}
          </Link>
        </Button>
      </div>

      {/* Attributes details list */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        <h3 className="text-muted-foreground text-xs font-medium uppercase tracking-wider">
          {t('listing.itemDetails')}
        </h3>
        <dl className="space-y-2.5 text-xs">
          {descriptor?.columns.map((col) => {
            const rawVal = item.values[col.key]
            const val = formatCellValue(rawVal, t('common.yes'), t('common.no'))
            const mono = isMonospaceKey(col.key)
            return (
              <div key={col.key} className="border-b border-border/40 pb-2 last:border-0">
                <dt className="text-muted-foreground text-[11px] font-medium">{col.label}</dt>
                <dd className={`mt-0.5 truncate text-foreground ${mono ? 'font-mono text-[11px]' : ''}`} title={val}>
                  {val}
                </dd>
              </div>
            )
          })}
        </dl>
      </div>

      {/* Quick Actions Footer */}
      <div className="border-t border-border/80 bg-muted/20 p-3 flex items-center justify-between gap-2">
        {type === 'user' && onLockToggle && (
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs gap-1.5 flex-1"
            onClick={() => onLockToggle(item.dn, !item.locked)}
          >
            {item.locked ? (
              <>
                <LockOpen className="size-3" aria-hidden />
                {t('listing.unlock')}
              </>
            ) : (
              <>
                <Lock className="size-3" aria-hidden />
                {t('listing.lock')}
              </>
            )}
          </Button>
        )}

        {onDeleteSingle && (
          <Button
            size="sm"
            variant="ghost"
            className="h-7 text-xs gap-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
            onClick={() => onDeleteSingle(item)}
          >
            <Trash2 className="size-3" aria-hidden />
            {t('common.delete')}
          </Button>
        )}
      </div>
    </aside>
  )
}

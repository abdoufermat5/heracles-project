import { Link } from '@tanstack/react-router'
import { Check, Copy, ExternalLink, Lock, LockOpen, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ObjectListItem, TypeDescriptor, TypeSummary } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { formatCellValue, isMonospaceKey } from './types'

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
  onClose,
  onCopyDn,
  onLockToggle,
  onDeleteSingle,
}: ListingPreviewPanelProps) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const nameAttr = descriptor?.name_attr ?? descriptor?.main_attr ?? 'cn'
  const title = item
    ? String(
        item.values[nameAttr] ??
          item.values[descriptor?.main_attr ?? ''] ??
          item.dn,
      )
    : t('listing.preview')

  const handleCopy = () => {
    if (!item) return
    onCopyDn(item.dn)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <aside
      aria-label={t('listing.preview')}
      className="flex w-80 shrink-0 flex-col overflow-hidden rounded-md border bg-card"
    >
      {/* Panel header bar */}
      <div className="flex h-10 items-center justify-between gap-2 border-b px-4">
        <h2 className="truncate text-body font-semibold" title={item ? title : undefined}>
          {title}
        </h2>
        <Button
          variant="ghost"
          size="icon-xs"
          className="text-muted-foreground hover:text-foreground"
          onClick={onClose}
          aria-label={t('listing.closePreview')}
        >
          <X aria-hidden />
        </Button>
      </div>

      {!item ? (
        <p className="p-4 text-body text-muted-foreground">{t('listing.itemDetails')}</p>
      ) : (
        <>
          {/* Status + primary action */}
          <div className="flex items-center gap-2 border-b px-4 py-2.5">
            {item.locked ? (
              <Badge variant="warning" className="h-5 gap-1 rounded-sm px-1.5 text-caption">
                <Lock className="size-3" aria-hidden />
                {t('listing.locked')}
              </Badge>
            ) : (
              <Badge variant="success" className="h-5 rounded-sm px-1.5 text-caption">
                {t('listing.filterActive')}
              </Badge>
            )}
            <Button asChild variant="outline" size="sm" className="ml-auto">
              <Link to="/types/$type/$dn" params={{ type, dn: item.dn }}>
                <ExternalLink aria-hidden />
                {t('listing.open')}
              </Link>
            </Button>
          </div>

          {/* Definition list */}
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            <dl className="space-y-3">
              <div>
                <dt className="label-caps">{t('listing.dnLabel')}</dt>
                <dd className="mt-1 flex items-start justify-between gap-2">
                  <span className="font-dn break-all text-foreground" title={item.dn}>
                    {item.dn}
                  </span>
                  <button
                    type="button"
                    onClick={handleCopy}
                    className="mt-0.5 inline-flex shrink-0 items-center rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
                    aria-label={t('listing.copyDn')}
                    title={t('listing.copyDn')}
                  >
                    {copied ? (
                      <Check className="size-3.5 text-success" aria-hidden />
                    ) : (
                      <Copy className="size-3.5" aria-hidden />
                    )}
                  </button>
                </dd>
              </div>

              {descriptor?.columns.map((col) => {
                const rawVal = item.values[col.key]
                const val = formatCellValue(rawVal, t('common.yes'), t('common.no'))
                const mono = isMonospaceKey(col.key)
                return (
                  <div key={col.key}>
                    <dt className="label-caps">{col.label}</dt>
                    <dd
                      className={`mt-1 truncate text-body text-foreground ${mono ? 'font-mono' : ''}`}
                      title={val}
                    >
                      {val}
                    </dd>
                  </div>
                )
              })}
            </dl>
          </div>

          {/* Quick actions footer */}
          <div className="flex items-center justify-between gap-2 border-t p-3">
            {type === 'user' && onLockToggle && (
              <Button
                size="sm"
                variant="outline"
                className="flex-1"
                onClick={() => onLockToggle(item.dn, !item.locked)}
              >
                {item.locked ? (
                  <>
                    <LockOpen className="size-3.5" aria-hidden />
                    {t('listing.unlock')}
                  </>
                ) : (
                  <>
                    <Lock className="size-3.5" aria-hidden />
                    {t('listing.lock')}
                  </>
                )}
              </Button>
            )}

            {onDeleteSingle && (
              <Button
                size="sm"
                variant="ghost"
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={() => onDeleteSingle(item)}
              >
                <Trash2 className="size-3.5" aria-hidden />
                {t('common.delete')}
              </Button>
            )}
          </div>
        </>
      )}
    </aside>
  )
}

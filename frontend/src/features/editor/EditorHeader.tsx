import { Link } from '@tanstack/react-router'
import {
  Check,
  ChevronLeft,
  Copy,
  FileCode2,
  Lock,
  MoreHorizontal,
  Pencil,
  Save,
  Trash2,
  Unlock,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import type { TypeDescriptor } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

interface Props {
  desc: TypeDescriptor
  dn: string | null
  title: string
  photo: string | null
  isCreate: boolean
  editing: boolean
  dirty: boolean
  canEdit: boolean
  canDelete: boolean
  isSubmitting: boolean
  accountLocked?: boolean
  onStartEdit: () => void
  onCancel: () => void
  onSave: () => void
  onDelete: () => void
  onViewLdif: () => void
  /** Open the create form prefilled from this object (needs create rights on the type). */
  onCopy?: () => void
  onToggleAccountLock?: () => void
}

/** Split a DN into RDN segments on unescaped commas. */
function splitDn(dn: string): string[] {
  const out: string[] = []
  let cur = ''
  for (let i = 0; i < dn.length; i += 1) {
    const ch = dn.charAt(i)
    if (ch === '\\' && i + 1 < dn.length) {
      cur += ch + dn.charAt(i + 1)
      i += 1
      continue
    }
    if (ch === ',') {
      out.push(cur)
      cur = ''
      continue
    }
    cur += ch
  }
  if (cur !== '') out.push(cur)
  return out
}

/** Split an RDN into its attribute name and value on the first unescaped "=". */
function splitRdn(rdn: string): { attr: string; value: string } {
  for (let i = 0; i < rdn.length; i += 1) {
    const ch = rdn.charAt(i)
    if (ch === '\\') {
      i += 1
      continue
    }
    if (ch === '=') return { attr: rdn.slice(0, i), value: rdn.slice(i + 1) }
  }
  return { attr: rdn, value: '' }
}

export function EditorHeader({
  desc,
  dn,
  title,
  photo,
  isCreate,
  editing,
  dirty,
  canEdit: canEditRights,
  canDelete: canDeleteRights,
  isSubmitting,
  accountLocked,
  onStartEdit,
  onCancel,
  onSave,
  onDelete,
  onViewLdif,
  onCopy,
  onToggleAccountLock,
}: Props) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const type = desc.name
  // type capability flags: Heracles-written types (audit events, ...) are view-only
  const canEdit = canEditRights && desc.editable !== false
  const canDelete = canDeleteRights && desc.deletable !== false

  const copyDn = async () => {
    if (!dn || typeof navigator === 'undefined' || !navigator.clipboard) return
    await navigator.clipboard.writeText(dn)
    setCopied(true)
    toast.success(t('editor.copied'))
    setTimeout(() => setCopied(false), 2000)
  }

  const segments = dn ? splitDn(dn) : []

  return (
    <header className="space-y-3 border-b pb-4">
      {/* Back to list */}
      <Link
        to="/types/$type"
        params={{ type }}
        className="inline-flex items-center gap-1 text-body text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronLeft className="size-3.5" aria-hidden />
        <span>{t('editor.backToList', { type: desc.label })}</span>
      </Link>

      {/* Main header row */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          {photo && (
            <img
              src={photo}
              alt={title}
              className="size-10 shrink-0 rounded-md border object-cover"
            />
          )}

          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-lg font-semibold tracking-tight text-foreground">
                {title}
              </h1>
              <Badge variant="neutral" className="h-5 rounded-sm px-1.5 text-caption">
                {desc.label}
              </Badge>
              {editing && !isCreate && (
                <Badge variant="outline" className="h-5 rounded-sm px-1.5 text-caption">
                  {t('editor.editing')}
                </Badge>
              )}
              {accountLocked && (
                <Badge
                  variant="warning"
                  className="h-5 gap-1 rounded-sm px-1.5 text-caption"
                >
                  <Lock className="size-3" aria-hidden />
                  {t('editor.accountLocked')}
                </Badge>
              )}
            </div>

            {dn && (
              <div className="flex items-center gap-1">
                <span
                  className="flex flex-wrap items-baseline font-mono text-xs select-all"
                  title={dn}
                >
                  {segments.map((rdn, i) => {
                    const { attr, value } = splitRdn(rdn)
                    return (
                      <span key={i} className="inline-flex items-baseline">
                        {i > 0 && <span className="text-muted-foreground">,</span>}
                        <span className="whitespace-nowrap">
                          <span className="text-muted-foreground">{attr}=</span>
                          <span className="text-foreground">{value}</span>
                        </span>
                      </span>
                    )
                  })}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => void copyDn()}
                  aria-label={t('editor.copyDn')}
                  title={t('editor.copyDn')}
                >
                  {copied ? (
                    <Check className="text-success" aria-hidden />
                  ) : (
                    <Copy aria-hidden />
                  )}
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          {!isCreate && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  size="icon-sm"
                  aria-label={t('editor.actions')}
                >
                  <MoreHorizontal aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                {onToggleAccountLock && (
                  <DropdownMenuItem onClick={onToggleAccountLock}>
                    {accountLocked ? (
                      <>
                        <Unlock className="size-3.5 text-muted-foreground" />
                        <span>{t('editor.unlockAccount')}</span>
                      </>
                    ) : (
                      <>
                        <Lock className="size-3.5 text-muted-foreground" />
                        <span>{t('editor.lockAccount')}</span>
                      </>
                    )}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={onViewLdif}>
                  <FileCode2 className="size-3.5 text-muted-foreground" />
                  <span>{t('editor.rawLdif')}</span>
                </DropdownMenuItem>
                {onCopy && desc.creatable !== false && (
                  <DropdownMenuItem onClick={onCopy}>
                    <Copy className="size-3.5 text-muted-foreground" />
                    <span>{t('copy.editorAction')}</span>
                  </DropdownMenuItem>
                )}
                {canDelete && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={onDelete}
                      className="text-destructive focus:text-destructive"
                    >
                      <Trash2 className="size-3.5" />
                      <span>{t('common.delete')}</span>
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}

          {editing ? (
            <>
              <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
                <X aria-hidden />
                {t('common.cancel')}
              </Button>
              {!dirty && (
                <Button
                  type="button"
                  size="sm"
                  disabled={!dirty || isSubmitting}
                  onClick={onSave}
                >
                  <Save aria-hidden />
                  {isCreate ? t('common.create') : t('common.save')}
                </Button>
              )}
            </>
          ) : (
            <>
              {canDelete && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                  onClick={onDelete}
                >
                  <Trash2 aria-hidden />
                  {t('common.delete')}
                </Button>
              )}
              {canEdit && (
                <Button type="button" size="sm" onClick={onStartEdit}>
                  <Pencil aria-hidden />
                  {t('common.edit')}
                </Button>
              )}
            </>
          )}
        </div>
      </div>
    </header>
  )
}

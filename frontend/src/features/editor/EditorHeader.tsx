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
  UserCheck,
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
import { TypeIcon } from '@/lib/icons'

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
  onDuplicate: () => void
  onViewLdif: () => void
  onToggleAccountLock?: () => void
}

export function EditorHeader({
  desc,
  dn,
  title,
  photo,
  isCreate,
  editing,
  dirty,
  canEdit,
  canDelete,
  isSubmitting,
  accountLocked,
  onStartEdit,
  onCancel,
  onSave,
  onDelete,
  onDuplicate,
  onViewLdif,
  onToggleAccountLock,
}: Props) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const type = desc.name

  const copyDn = async () => {
    if (!dn || typeof navigator === 'undefined' || !navigator.clipboard) return
    await navigator.clipboard.writeText(dn)
    setCopied(true)
    toast.success(t('editor.copied'))
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <header className="space-y-3">
      {/* Breadcrumb back to list */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Link
          to="/types/$type"
          params={{ type }}
          className="hover:text-foreground inline-flex items-center gap-1 transition-colors"
        >
          <ChevronLeft className="size-3.5" />
          <span>{t('editor.backToList', { type: desc.label })}</span>
        </Link>
      </nav>

      {/* Main header row */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3.5">
          {/* Avatar / Photo / Type Icon */}
          <div className="bg-primary-soft text-primary border-border flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-xl border shadow-xs">
            {photo ? (
              <img src={photo} alt={title} className="size-full object-cover" />
            ) : (
              <TypeIcon name={desc.icon} className="size-6" />
            )}
          </div>

          {/* Title & Monospace DN */}
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-xl font-semibold tracking-tight text-foreground">{title}</h1>
              <Badge variant="outline" className="text-xs font-normal">
                {desc.label}
              </Badge>
              {editing && !isCreate && (
                <Badge variant="outline" className="text-xs">
                  {t('editor.editing')}
                </Badge>
              )}
              {accountLocked && (
                <Badge variant="outline" className="border-warning/40 text-warning gap-1 text-xs">
                  <Lock className="size-3" aria-hidden />
                  {t('editor.accountLocked')}
                </Badge>
              )}
            </div>

            {dn && (
              <div className="flex items-center gap-1.5">
                <span className="font-dn text-muted-foreground truncate text-xs select-all" title={dn}>
                  {dn}
                </span>
                <button
                  type="button"
                  onClick={copyDn}
                  aria-label={t('editor.copyDn')}
                  title={t('editor.copyDn')}
                  className="hover:bg-accent text-muted-foreground hover:text-foreground rounded p-1 transition-colors"
                >
                  {copied ? <Check className="size-3 text-success" /> : <Copy className="size-3" />}
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          {/* Actions dropdown for extra operations (view LDIF, duplicate, lock account, delete) */}
          {!isCreate && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="size-8"
                  aria-label={t('editor.actions')}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                {onToggleAccountLock && (
                  <DropdownMenuItem onClick={onToggleAccountLock}>
                    {accountLocked ? (
                      <>
                        <Unlock className="size-4 text-success" />
                        <span>{t('editor.unlockAccount')}</span>
                      </>
                    ) : (
                      <>
                        <Lock className="size-4 text-warning" />
                        <span>{t('editor.lockAccount')}</span>
                      </>
                    )}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={onDuplicate}>
                  <UserCheck className="size-4" />
                  <span>{t('editor.duplicate')}</span>
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onViewLdif}>
                  <FileCode2 className="size-4" />
                  <span>{t('editor.rawLdif')}</span>
                </DropdownMenuItem>
                {canDelete && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={onDelete}
                      className="text-destructive focus:text-destructive"
                    >
                      <Trash2 className="size-4" />
                      <span>{t('common.delete')}</span>
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}

          {/* Primary edit / save buttons */}
          {editing ? (
            <>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 gap-1.5"
                onClick={onCancel}
              >
                <X className="size-4" />
                {t('common.cancel')}
              </Button>
              {!dirty && (
                <Button
                  type="button"
                  size="sm"
                  className="h-8 gap-1.5"
                  disabled={!dirty || isSubmitting}
                  onClick={onSave}
                >
                  <Save className="size-4" />
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
                  className="h-8 gap-1.5"
                  onClick={onDelete}
                >
                  <Trash2 className="size-4" />
                  {t('common.delete')}
                </Button>
              )}
              {canEdit && (
                <Button
                  type="button"
                  size="sm"
                  className="h-8 gap-1.5"
                  onClick={onStartEdit}
                >
                  <Pencil className="size-4" />
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

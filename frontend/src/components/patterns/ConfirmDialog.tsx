import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

/**
 * Confirmation before an action. Destructive actions are red; with
 * `confirmText`, people type that text first (for irreversible deletions).
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  destructive = false,
  confirmText,
  pending = false,
  onConfirm,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: React.ReactNode
  description?: React.ReactNode
  confirmLabel: string
  destructive?: boolean
  confirmText?: string
  pending?: boolean
  onConfirm: () => void
  children?: React.ReactNode
}) {
  const { t } = useTranslation()
  const [typed, setTyped] = useState('')
  const matches = !confirmText || typed.trim() === confirmText

  return (
    <AlertDialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setTyped('')
        onOpenChange(o)
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description && <AlertDialogDescription>{description}</AlertDialogDescription>}
        </AlertDialogHeader>
        {children}
        {confirmText && (
          <label className="grid gap-1.5 text-small text-muted-foreground">
            <span>{t('patterns.typeToConfirm', { text: confirmText })}</span>
            <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
          </label>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{t('patterns.cancel')}</AlertDialogCancel>
          <Button
            type="button"
            variant={destructive ? 'destructive' : 'default'}
            disabled={!matches || pending}
            onClick={onConfirm}
          >
            {pending && <Loader2 className="animate-spin" aria-hidden />}
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

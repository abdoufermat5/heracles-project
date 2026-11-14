import { useQueryClient } from '@tanstack/react-query'
import { Check, Copy, KeyRound, Loader2, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { generatePassword } from '@/lib/password'

interface ResetPasswordDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  userDn: string
  userName: string
  onSuccess?: () => void
}

export function ResetPasswordDialog({
  open,
  onOpenChange,
  userDn,
  userName,
  onSuccess,
}: ResetPasswordDialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [password, setPassword] = useState('')
  const [requireChange, setRequireChange] = useState(true)
  const [copied, setCopied] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const handleGenerate = () => {
    const pw = generatePassword(16)
    setPassword(pw)
    void navigator.clipboard?.writeText(pw).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const handleCopy = () => {
    if (!password) return
    void navigator.clipboard?.writeText(password).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const handleSubmit = async () => {
    if (!password.trim()) return
    setSubmitting(true)
    try {
      await api.patchObject('user', userDn, {
        tabs: {
          main: {
            active: true,
            values: {
              userPassword: password,
              forcePasswordChange: requireChange,
            },
          },
        },
      })
      toast.success(t('peopleUI.userProfile.resetPasswordDialog.success'))
      void queryClient.invalidateQueries({ queryKey: ['objects', 'user'] })
      onSuccess?.()
      onOpenChange(false)
      setPassword('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('peopleUI.errors.resetPassword'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="size-5 text-primary" aria-hidden />
            <span>{t('peopleUI.userProfile.resetPasswordDialog.title', { name: userName })}</span>
          </DialogTitle>
          <DialogDescription>
            {t('peopleUI.userProfile.resetPasswordDialog.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="new-pw">
              {t('peopleUI.userProfile.resetPasswordDialog.passwordLabel')}
            </Label>
            <Input
              id="new-pw"
              type="text"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t('peopleUI.userProfile.resetPasswordDialog.passwordPlaceholder')}
              className="w-full font-mono text-small"
              autoComplete="off"
            />
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button type="button" variant="outline" size="sm" onClick={handleGenerate}>
                <Sparkles className="size-3.5" />
                {t('peopleUI.userProfile.resetPasswordDialog.generate')}
              </Button>
              {password && (
                <Button
                  type="button"
                  variant="outline"
                  size="icon-sm"
                  onClick={handleCopy}
                  aria-label={t('peopleUI.userProfile.resetPasswordDialog.copy')}
                  title={t('peopleUI.userProfile.resetPasswordDialog.copy')}
                >
                  {copied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
                </Button>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 pt-1">
            <Checkbox
              id="require-change"
              checked={requireChange}
              onCheckedChange={(c) => setRequireChange(c === true)}
            />
            <Label htmlFor="require-change" className="cursor-pointer text-small">
              {t('peopleUI.userProfile.resetPasswordDialog.requireChange')}
            </Label>
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={submitting}
            onClick={() => onOpenChange(false)}
          >
            {t('common.cancel')}
          </Button>
          <Button
            type="button"
            disabled={!password.trim() || submitting}
            onClick={() => void handleSubmit()}
          >
            {submitting && <Loader2 className="animate-spin" aria-hidden />}
            {t('peopleUI.userProfile.resetPasswordDialog.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

import { Check, Eye, EyeOff, KeyRound, Sparkles, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { usePatchObject } from '@/api/hooks'
import { SectionCard } from '@/components/patterns/SectionCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ReauthDialog } from '@/features/me/ReauthDialog'
import { generatePassword, passwordStrength } from '@/lib/password'
import { cn } from '@/lib/utils'

const STRENGTH_COLORS = ['bg-muted', 'bg-destructive', 'bg-warning', 'bg-primary', 'bg-success']
const STRENGTH_KEYS = [
  'settingsUI.portal.strengthVeryWeak',
  'settingsUI.portal.strengthWeak',
  'settingsUI.portal.strengthFair',
  'settingsUI.portal.strengthGood',
  'settingsUI.portal.strengthStrong',
] as const

export function PasswordSection({ userDn, allowed = true }: { userDn: string; allowed?: boolean }) {
  const { t } = useTranslation()
  const patch = usePatchObject('user', userDn)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /** Set when the server asks to confirm the password first; retried once confirmed. */
  const [needsReauth, setNeedsReauth] = useState(false)

  const score = passwordStrength(newPassword)
  const isMatching = newPassword !== '' && confirmPassword !== '' && newPassword === confirmPassword
  const isMismatch = confirmPassword !== '' && newPassword !== confirmPassword

  const canSubmit = newPassword !== '' && isMatching && !patch.isPending

  const onGenerate = () => {
    const pw = generatePassword(16)
    setNewPassword(pw)
    setConfirmPassword(pw)
    setShowPassword(true)
    setError(null)
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      void navigator.clipboard.writeText(pw).catch(() => undefined)
    }
    toast.success(t('fields.passwordGenerated'))
  }

  const submit = async () => {
    setError(null)
    try {
      await patch.mutateAsync({
        tabs: {
          main: {
            active: true,
            values: { userPassword: newPassword },
          },
        },
      })
      toast.success(t('settingsUI.portal.passwordUpdated'))
      setNewPassword('')
      setConfirmPassword('')
      setShowPassword(false)
    } catch (err) {
      if (isApiError(err) && err.code === 'reauth_required') {
        setNeedsReauth(true)
        return
      }
      setError(isApiError(err) ? err.message : t('common.error'))
      toast.error(isApiError(err) ? err.message : t('common.error'))
    }
  }

  return (
    <SectionCard
      id="portal-password"
      title={t('settingsUI.portal.passwordTitle')}
      description={t('settingsUI.portal.passwordSubtitle')}
    >
      {!allowed ? (
        <p className="text-small text-muted-foreground">{t('settingsUI.portal.passwordNotAllowed')}</p>
      ) : (
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (!isMatching) {
            setError(t('settingsUI.portal.passwordsDoNotMatch'))
            return
          }
          void submit()
        }}
        className="max-w-lg space-y-4"
      >
        {/* New password input */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="new-password">{t('settingsUI.portal.newPassword')}</Label>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 text-caption gap-1 text-muted-foreground hover:text-foreground"
              onClick={onGenerate}
            >
              <Sparkles className="size-3 text-primary" aria-hidden />
              <span>{t('settingsUI.portal.generatePassword')}</span>
            </Button>
          </div>
          <div className="relative flex items-center">
            <Input
              id="new-password"
              type={showPassword ? 'text' : 'password'}
              value={newPassword}
              onChange={(e) => {
                setNewPassword(e.target.value)
                setError(null)
              }}
              className="pr-10 font-mono text-small"
              placeholder="••••••••••••"
              autoComplete="new-password"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-2.5 text-muted-foreground hover:text-foreground outline-none"
              aria-label={showPassword ? t('settingsUI.portal.hidePassword') : t('settingsUI.portal.showPassword')}
            >
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
        </div>

        {/* Strength meter */}
        {newPassword && (
          <div className="space-y-1 pt-1">
            <div className="flex h-1.5 w-full gap-1 overflow-hidden rounded-full bg-muted">
              {[1, 2, 3, 4].map((step) => (
                <div
                  key={step}
                  className={cn(
                    'h-full flex-1 transition-colors duration-200',
                    score >= step ? STRENGTH_COLORS[score] : 'bg-transparent',
                  )}
                />
              ))}
            </div>
            <p className="text-micro text-muted-foreground">
              {t('settingsUI.portal.strength')}: <span className="font-medium text-foreground">{t(STRENGTH_KEYS[score] ?? 'settingsUI.portal.strengthFair')}</span>
            </p>
          </div>
        )}

        {/* Confirm password input */}
        <div className="space-y-1.5">
          <Label htmlFor="confirm-password">{t('settingsUI.portal.confirmPassword')}</Label>
          <Input
            id="confirm-password"
            type={showPassword ? 'text' : 'password'}
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(e.target.value)
              setError(null)
            }}
            className={cn('font-mono text-small', isMismatch && 'border-destructive')}
            placeholder="••••••••••••"
            autoComplete="new-password"
          />
        </div>

        {/* Live policy check: passwords match */}
        <div className="space-y-1.5 rounded-md border bg-muted/20 p-3 text-caption text-muted-foreground">
          <div className="flex items-center gap-2">
            {isMatching ? (
              <Check className="size-3.5 text-success" />
            ) : isMismatch ? (
              <X className="size-3.5 text-destructive" />
            ) : (
              <span className="size-3.5 rounded-full border border-muted-foreground/40" />
            )}
            <span className={cn(isMatching && 'text-foreground font-medium', isMismatch && 'text-destructive')}>
              {isMismatch
                ? t('settingsUI.portal.passwordsDoNotMatch')
                : t('settingsUI.portal.passwordsMustMatch')}
            </span>
          </div>
        </div>

        {error && (
          <p role="alert" className="text-small text-destructive">
            {error}
          </p>
        )}

        <Button type="submit" disabled={!canSubmit} className="gap-2">
          <KeyRound className="size-4" />
          {t('settingsUI.portal.changePassword')}
        </Button>
      </form>
      )}
      <ReauthDialog
        open={needsReauth}
        body={t('reauth.passwordChangeBody')}
        onCancel={() => setNeedsReauth(false)}
        onConfirmed={() => {
          setNeedsReauth(false)
          void submit()
        }}
      />
    </SectionCard>
  )
}

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
import { newPasswordError, usePasswordPolicy } from '@/features/auth/passwordPolicy'
import { ReauthDialog } from '@/features/me/ReauthDialog'
import { FieldError, useLiveForm, type FieldErrors } from '@/lib/liveForm'
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

export function PasswordSection({
  userDn,
  username,
  allowed = true,
}: {
  userDn: string
  /** Login of the account: the hidden login field password managers expect. */
  username: string
  allowed?: boolean
}) {
  const { t } = useTranslation()
  const patch = usePatchObject('user', userDn)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /** What the server refused, under the same field as the browser's own messages. */
  const [refused, setRefused] = useState<FieldErrors | undefined>(undefined)
  const policy = usePasswordPolicy()
  const form = useLiveForm(
    'pw',
    { password: newPassword, confirm: confirmPassword },
    (v) => {
      const out: FieldErrors = {}
      const problem = newPasswordError(v.password, policy)
      if (problem) out.password = problem
      else if (v.confirm !== v.password)
        out.confirm = t('settingsUI.portal.passwordsDoNotMatch')
      return out
    },
    refused,
  )
  /** Set when the server asks to confirm the password first; retried once confirmed. */
  const [needsReauth, setNeedsReauth] = useState(false)

  const score = passwordStrength(newPassword)
  const isMatching = newPassword !== '' && confirmPassword !== '' && newPassword === confirmPassword
  const isMismatch = confirmPassword !== '' && newPassword !== confirmPassword

  const canSubmit =
    newPassword !== '' && isMatching && !patch.isPending && Object.keys(form.errors).length === 0

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
    setRefused(undefined)
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
      const fields = isApiError(err) ? (err.fields ?? {}) : {}
      const refusedPassword = Object.entries(fields).find(([key]) => /(^|\.)userPassword$/.test(key))
      if (refusedPassword) {
        // a policy verdict belongs under the field, not in a toast
        setRefused({ password: refusedPassword[1] })
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
          if (!form.attempt() || !isMatching) return
          void submit()
        }}
        className="max-w-lg space-y-4"
      >
        {/* Password managers (and Chrome) expect a login field next to a password one. */}
        <input
          type="text"
          name="username"
          autoComplete="username"
          value={username}
          readOnly
          tabIndex={-1}
          className="hidden"
          aria-hidden="true"
        />
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
              {...form.field('password')}
              className="pr-10 font-mono text-small"
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
          <p className="text-caption text-muted-foreground">
            {t('passwordPolicy.hint', { count: policy.min_length })}
          </p>
          <FieldError formId="pw" name="password" form={form} />
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
              form.touch('confirm')
              setError(null)
            }}
            {...form.field('confirm')}
            className={cn('font-mono text-small', isMismatch && 'border-destructive')}
            autoComplete="new-password"
          />
          <FieldError formId="pw" name="confirm" form={form} />
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
              {t('settingsUI.portal.passwordsMustMatch')}
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

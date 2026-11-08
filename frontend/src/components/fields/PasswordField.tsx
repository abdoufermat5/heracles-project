import { Eye, EyeOff, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { generatePassword, passwordStrength } from '@/lib/password'
import { cn } from '@/lib/utils'
import type { FieldInputProps } from './types'

const colors = ['bg-muted', 'bg-destructive', 'bg-warning', 'bg-primary', 'bg-success']

export function PasswordField({ p }: { p: FieldInputProps }) {
  const { t } = useTranslation()
  const [show, setShow] = useState(false)
  const [localConfirm, setLocalConfirm] = useState('')
  const pw = typeof p.value === 'string' ? p.value : ''
  const confirm = p.confirm ?? localConfirm
  const setConfirm = p.onConfirmChange ?? setLocalConfirm
  const score = passwordStrength(pw)
  const mismatch = pw !== '' && confirm !== '' && pw !== confirm

  const onGenerate = () => {
    const generated = generatePassword(16)
    p.onChange(generated)
    setConfirm(generated)
    setShow(true)
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      void navigator.clipboard.writeText(generated).catch(() => undefined)
    }
    toast.success(t('fields.passwordGenerated'))
  }

  if (p.readOnly) {
    return (
      <div className="flex h-8 items-center text-[13px] text-muted-foreground select-none">
        ••••••••
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="relative flex items-center">
        <Input
          id={p.id}
          type={show ? 'text' : 'password'}
          value={pw}
          onChange={(e) => {
            const v = e.target.value
            p.onChange(v === '' ? null : v)
            if (v === '') setConfirm('')
          }}
          disabled={p.readOnly}
          placeholder={t('fields.passwordUnchanged')}
          autoComplete="new-password"
          aria-invalid={p.invalid || undefined}
          aria-describedby={p.error ? `${p.id}-error` : undefined}
          className="h-8 pr-16 text-[13px]"
        />
        <div className="absolute right-1 flex items-center gap-0.5">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={onGenerate}
            aria-label={t('fields.generatePassword')}
            title={t('fields.generatePassword')}
          >
            <Sparkles className="size-3.5 text-muted-foreground" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={() => setShow((s) => !s)}
            aria-label={show ? t('fields.hidePassword') : t('fields.showPassword')}
            title={show ? t('fields.hidePassword') : t('fields.showPassword')}
          >
            {show ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
          </Button>
        </div>
      </div>

      {pw !== '' && (
        <>
          <div
            role="meter"
            aria-label={t('fields.passwordStrength')}
            aria-valuemin={0}
            aria-valuemax={4}
            aria-valuenow={score}
            aria-valuetext={t(`fields.strength.${score}`)}
            className="flex items-center gap-2"
          >
            <div className="flex flex-1 gap-1">
              {[1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className={cn('h-1 flex-1 rounded-sm transition-colors', i <= score ? colors[score] : 'bg-muted')}
                />
              ))}
            </div>
            <span className="w-16 text-right text-[11px] text-muted-foreground">
              {t(`fields.strength.${score}`)}
            </span>
          </div>

          <Input
            type={show ? 'text' : 'password'}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder={t('fields.passwordConfirm')}
            aria-label={t('fields.passwordConfirm')}
            autoComplete="new-password"
            aria-invalid={mismatch || undefined}
            className="h-8 text-[13px]"
          />

          {mismatch && (
            <p role="alert" className="text-destructive text-xs">
              {t('validation.passwordMismatch')}
            </p>
          )}
        </>
      )}
    </div>
  )
}

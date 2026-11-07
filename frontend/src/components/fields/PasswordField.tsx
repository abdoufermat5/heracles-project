import { Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { passwordStrength } from '@/lib/password'
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

  return (
    <div className="space-y-2">
      <div className="relative">
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
          placeholder={p.readOnly ? '••••••••' : t('fields.passwordUnchanged')}
          autoComplete="new-password"
          aria-invalid={p.invalid || undefined}
          aria-describedby={p.error ? `${p.id}-error` : undefined}
          className="pr-10"
        />
        {!p.readOnly && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="absolute top-0.5 right-0.5 size-8"
            onClick={() => setShow((s) => !s)}
            aria-label={show ? t('fields.hidePassword') : t('fields.showPassword')}
          >
            {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </Button>
        )}
      </div>
      {!p.readOnly && pw !== '' && (
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
                  className={cn('h-1 flex-1 rounded-full', i <= score ? colors[score] : 'bg-muted')}
                />
              ))}
            </div>
            <span className="text-muted-foreground w-16 text-xs">{t(`fields.strength.${score}`)}</span>
          </div>
          <Input
            type={show ? 'text' : 'password'}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder={t('fields.passwordConfirm')}
            aria-label={t('fields.passwordConfirm')}
            autoComplete="new-password"
            aria-invalid={mismatch || undefined}
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

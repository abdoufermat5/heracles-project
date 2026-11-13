import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useRouter, useSearch } from '@tanstack/react-router'
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { z } from 'zod'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useDirectories } from '@/api/hooks'
import type { SecondFactorMethod } from '@/api/types'
import { Logo } from '@/components/Logo'
import { useBranding } from './branding'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { APP_VERSION } from '@/lib/appVersion'
import { cn } from '@/lib/utils'
import { getAssertion, WebAuthnClientError, webauthnSupported } from '@/lib/webauthn'
import { SsoEntry } from './SsoEntry'

function BrandMark({ tone }: { tone: 'default' | 'onPrimary' }) {
  const { data: brand } = useBranding()
  if (brand?.logo_url)
    return (
      <img
        src={brand.logo_url}
        alt={brand.organization || 'Heracles'}
        className="h-8 w-auto max-w-48 object-contain"
      />
    )
  return <Logo tone={tone} />
}

/**
 * Sign-in pages: the organisation on one side, the form on the other. On small
 * screens the brand panel folds into a header above the form.
 */
export function AuthLayout({
  title,
  subtitle,
  wide = false,
  children,
}: {
  title: string
  subtitle?: string
  /** a roomier column, for multi-step flows such as the first-run setup */
  wide?: boolean
  children: React.ReactNode
}) {
  const { t } = useTranslation()
  const { data: brand } = useBranding()
  const organization = brand?.organization || ''
  return (
    <div className="grid min-h-dvh bg-background lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="relative hidden overflow-hidden bg-brand-panel text-brand-panel-foreground lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.07] [background-image:radial-gradient(currentColor_1px,transparent_1px)] [background-size:22px_22px]"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -right-24 -bottom-24 size-96 rounded-full bg-brand-panel-foreground/10 blur-3xl"
        />
        <div className="relative">
          <BrandMark tone="onPrimary" />
        </div>
        <div className="relative max-w-md space-y-4">
          <h2 className="text-display font-semibold tracking-tight">
            {organization || t('auth.brandHeadline')}
          </h2>
          <p className="text-lead text-brand-panel-foreground/80">
            {brand?.tagline || t('auth.brandTagline')}
          </p>
        </div>
        <div className="relative flex items-center justify-between text-small text-brand-panel-foreground/70">
          <span>{organization ? t('auth.poweredBy') : t('auth.brandFooter')}</span>
          <span className="font-mono">v{APP_VERSION}</span>
        </div>
      </aside>

      <div className="flex min-h-dvh flex-col">
        <header className="flex h-16 shrink-0 items-center px-6 lg:hidden">
          <BrandMark tone="default" />
        </header>
        <main className="flex flex-1 items-center justify-center px-6 py-10">
          <div className={cn('w-full', wide ? 'max-w-xl' : 'max-w-[380px]')}>
            <div className="space-y-1.5">
              <h1 className="text-title font-semibold tracking-tight text-foreground">{title}</h1>
              {subtitle && <p className="text-body text-muted-foreground">{subtitle}</p>}
            </div>
            <div className="mt-7">{children}</div>
          </div>
        </main>
        <footer className="flex h-12 shrink-0 items-center justify-center px-6 lg:hidden">
          <span className="font-mono text-caption text-muted-foreground">Heracles v{APP_VERSION}</span>
        </footer>
      </div>
    </div>
  )
}

function Field({
  id,
  label,
  error,
  children,
}: {
  id: string
  label: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-body font-medium text-foreground">
        {label}
      </Label>
      {children}
      {error && (
        <p id={`${id}-error`} role="alert" className="mt-1 text-body font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

function FormError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-sm border border-destructive/30 bg-destructive-soft p-2.5 text-body text-destructive"
    >
      <AlertCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span className="leading-snug">{message}</span>
    </div>
  )
}

function PasswordInput({
  id,
  error,
  className,
  onKeyDown,
  onKeyUp,
  onBlur,
  ...props
}: React.ComponentProps<"input"> & { error?: boolean }) {
  const { t } = useTranslation()
  const [show, setShow] = useState(false)
  const [capsLock, setCapsLock] = useState(false)

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    setCapsLock(e.getModifierState('CapsLock'))
    onKeyDown?.(e)
  }

  return (
    <div className="space-y-1">
      <div className="relative flex items-center">
        <Input
          id={id}
          type={show ? 'text' : 'password'}
          onKeyDown={handleKey}
          onKeyUp={(e) => {
            setCapsLock(e.getModifierState('CapsLock'))
            onKeyUp?.(e)
          }}
          onBlur={(e) => {
            setCapsLock(false)
            onBlur?.(e)
          }}
          className={cn('pr-8 font-mono', error && 'border-destructive', className)}
          {...props}
        />
        <button
          type="button"
          tabIndex={-1}
          onClick={() => setShow((s) => !s)}
          aria-label={show ? t('fields.hidePassword') : t('fields.showPassword')}
          className="text-muted-foreground hover:text-foreground absolute right-2 size-6 flex items-center justify-center rounded outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {show ? <EyeOff className="size-3.5" aria-hidden /> : <Eye className="size-3.5" aria-hidden />}
        </button>
      </div>
      {capsLock && (
        <div className="flex items-center gap-1 text-caption text-warning" role="status">
          <AlertTriangle className="size-3 shrink-0" aria-hidden />
          <span>{t('auth.capsLock')}</span>
        </div>
      )}
    </div>
  )
}

/** 6-box OTP verification input with auto-advance and paste support */
function OtpInput({
  value,
  onChange,
  id = 'code',
  autoFocus = true,
}: {
  value: string
  onChange: (val: string) => void
  id?: string
  autoFocus?: boolean
}) {
  const inputs = useRef<(HTMLInputElement | null)[]>([])
  const chars = Array.from({ length: 6 }, (_, i) => value[i] ?? '')

  const handleChange = (index: number, val: string) => {
    // If multiple characters typed or pasted directly into input
    const digits = val.replace(/\D/g, '')
    if (digits.length > 1) {
      handlePaste(digits)
      return
    }

    const nextChars = [...chars]
    nextChars[index] = digits.slice(-1)
    const nextVal = nextChars.join('')
    onChange(nextVal)

    if (digits && index < 5) {
      inputs.current[index + 1]?.focus()
    }
  }

  const handleKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace') {
      if (!chars[index] && index > 0) {
        inputs.current[index - 1]?.focus()
        const nextChars = [...chars]
        nextChars[index - 1] = ''
        onChange(nextChars.join(''))
      } else {
        const nextChars = [...chars]
        nextChars[index] = ''
        onChange(nextChars.join(''))
      }
    } else if (e.key === 'ArrowLeft' && index > 0) {
      inputs.current[index - 1]?.focus()
    } else if (e.key === 'ArrowRight' && index < 5) {
      inputs.current[index + 1]?.focus()
    }
  }

  const handlePaste = (pasted: string) => {
    const clean = pasted.replace(/\D/g, '').slice(0, 6)
    if (clean) {
      onChange(clean)
      const targetIdx = Math.min(clean.length, 5)
      inputs.current[targetIdx]?.focus()
    }
  }

  return (
    <div
      role="group"
      className="flex items-center justify-between gap-1.5"
    >
      {Array.from({ length: 6 }).map((_, i) => (
        <input
          key={i}
          id={i === 0 ? id : undefined}
          ref={(el) => {
            inputs.current[i] = el
          }}
          type="text"
          inputMode="numeric"
          autoComplete={i === 0 ? 'one-time-code' : 'off'}
          autoFocus={autoFocus && i === 0}
          maxLength={1}
          value={chars[i]}
          onChange={(e) => handleChange(i, e.target.value)}
          onKeyDown={(e) => handleKeyDown(i, e)}
          onPaste={(e) => {
            e.preventDefault()
            handlePaste(e.clipboardData.getData('text'))
          }}
          aria-label={i === 0 ? undefined : `Digit ${i + 1}`}
          className="size-10 rounded-md border border-input bg-card text-center font-mono text-base font-semibold outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/25"
        />
      ))}
    </div>
  )
}

function Submit({ pending, children }: { pending: boolean; children: React.ReactNode }) {
  return (
    <Button type="submit" className="h-9 w-full" disabled={pending}>
      {pending && <Loader2 className="size-3.5 animate-spin mr-1.5" aria-hidden />}
      {children}
    </Button>
  )
}

export function LoginPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const router = useRouter()
  const qc = useQueryClient()
  const search = useSearch({ from: '/login' })
  const dirs = useDirectories()
  const [error, setError] = useState<string | null>(null)

  const schema = z.object({
    directory: z.string(),
    username: z.string().min(1, t('validation.required')),
    password: z.string().min(1, t('validation.required')),
  })
  type Values = z.infer<typeof schema>
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { directory: '', username: '', password: '' },
  })

  // Set default directory when dirs data loads
  const currentDir = dirs.data?.[0]?.id ?? ''
  useEffect(() => {
    if (currentDir && !form.getValues('directory')) {
      form.setValue('directory', currentDir)
    }
  }, [currentDir, form])

  // a new session: nothing cached for a previous one (another account) may be shown
  const signedIn = async () => {
    qc.clear()
    if (search.redirect) router.history.push(search.redirect)
    else await navigate({ to: '/' })
  }

  const onSubmit = form.handleSubmit(async (v) => {
    setError(null)
    try {
      const selectedDir = v.directory || currentDir
      const res = await api.login({ ...v, directory: selectedDir })
      if (res.status === 'second_factor') {
        await navigate({
          to: '/login/second-factor',
          search: { methods: (res.methods ?? ['totp']).join(','), redirect: search.redirect },
        })
        return
      }
      await signedIn()
    } catch (e) {
      setError(isApiError(e) && e.status !== 401 ? e.message : t('auth.invalidCredentials'))
    }
  })

  return (
    <AuthLayout title={t('auth.loginTitle')} subtitle={t('auth.loginSubtitle')}>
      <SsoEntry next={search.redirect} failed={search.sso_error === '1'} />
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-4" noValidate>
        <FormError message={error} />
        <Field id="directory" label={t('auth.directory')} error={form.formState.errors.directory?.message}>
          <select
            id="directory"
            {...form.register('directory')}
            className="h-9 w-full rounded-md border border-input bg-card px-2.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
          >
            {dirs.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.label}
              </option>
            ))}
          </select>
        </Field>
        <Field id="username" label={t('auth.username')} error={form.formState.errors.username?.message}>
          <Input id="username" autoComplete="username" autoFocus {...form.register('username')} />
        </Field>
        <Field id="password" label={t('auth.password')} error={form.formState.errors.password?.message}>
          <PasswordInput
            id="password"
            autoComplete="current-password"
            error={Boolean(form.formState.errors.password)}
            {...form.register('password')}
          />
        </Field>
        <Submit pending={form.formState.isSubmitting}>{t('auth.signIn')}</Submit>
        <p className="pt-1 text-center text-body text-muted-foreground">
          <Link to="/recovery" className="text-body text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
            {t('auth.forgotPassword')}
          </Link>
        </p>
      </form>
    </AuthLayout>
  )
}

export function SecondFactorPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const router = useRouter()
  const qc = useQueryClient()
  const search = useSearch({ from: '/login/second-factor' })
  const methods = (search.methods?.split(',') ?? ['totp']).filter(
    (m): m is SecondFactorMethod => m === 'totp' || m === 'recovery' || m === 'webauthn',
  )
  const [method, setMethod] = useState<SecondFactorMethod>(methods[0] ?? 'totp')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const finish = async () => {
    // a new session: nothing cached for a previous one may be shown
    qc.clear()
    if (search.redirect) router.history.push(search.redirect)
    else await navigate({ to: '/' })
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (method === 'webauthn') {
      await signInWithKey()
      return
    }
    if (!code.trim()) {
      setError(t('validation.required'))
      return
    }
    setPending(true)
    setError(null)
    try {
      await api.secondFactor({ method, code: code.trim() })
      await finish()
    } catch (err) {
      setError(isApiError(err) && err.status !== 401 ? err.message : t('auth.invalidCode'))
    } finally {
      setPending(false)
    }
  }

  async function signInWithKey() {
    setPending(true)
    setError(null)
    try {
      const { options } = await api.webauthnOptions()
      const credential = await getAssertion(options)
      await api.secondFactor({ method: 'webauthn', credential })
      await finish()
    } catch (err) {
      if (err instanceof WebAuthnClientError) {
        setError(t(`auth.webauthn_${err.reason}`))
      } else {
        setError(isApiError(err) && err.status !== 401 ? err.message : t('auth.webauthn_failed'))
      }
    } finally {
      setPending(false)
    }
  }

  return (
    <AuthLayout title={t('auth.secondFactorTitle')} subtitle={t(`auth.secondFactorHelp_${method}`)}>
      <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate>
        <FormError message={error} />
        {methods.length > 1 && (
          <div role="group" aria-label={t('auth.method')} className="grid grid-cols-2 gap-1 rounded-md border bg-card p-0.5">
            {methods.map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={method === m}
                onClick={() => {
                  setMethod(m)
                  setCode('')
                  setError(null)
                }}
                className={cn(
                  'h-7 rounded-sm text-body font-medium transition-colors',
                  method === m
                    ? 'bg-primary-soft font-semibold text-foreground'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {t(`auth.method_${m}`)}
              </button>
            ))}
          </div>
        )}

        {method === 'webauthn' ? (
          <>
            {!webauthnSupported() && (
              <p className="text-body text-muted-foreground">{t('auth.webauthn_unsupported')}</p>
            )}
            <Button
              type="submit"
              className="h-9 w-full text-body"
              disabled={pending || !webauthnSupported()}
            >
              {pending ? <Loader2 className="size-3.5 animate-spin" /> : <KeyRound className="size-3.5" />}
              {t('auth.useSecurityKey')}
            </Button>
          </>
        ) : (
        <Field id="code" label={t(`auth.code_${method}`)}>
          {method === 'totp' ? (
            <OtpInput value={code} onChange={setCode} id="code" />
          ) : (
            <Input
              id="code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoComplete="one-time-code"
              autoFocus
              className="font-mono text-center text-sm"
              maxLength={64}
            />
          )}
        </Field>
        )}

        {method !== 'webauthn' && <Submit pending={pending}>{t('auth.verify')}</Submit>}
        <p className="pt-1 text-center text-body text-muted-foreground">
          <Link to="/login" className="text-body text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
            {t('auth.backToLogin')}
          </Link>
        </p>
      </form>
    </AuthLayout>
  )
}

export function RecoveryRequestPage() {
  const { t } = useTranslation()
  const dirs = useDirectories()
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const schema = z.object({ email: z.string().email(t('validation.email')) })
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema), defaultValues: { email: '' } })

  const onSubmit = form.handleSubmit(async (v) => {
    setError(null)
    try {
      await api.requestRecovery({ directory: dirs.data?.[0]?.id ?? 'main', email: v.email })
      setDone(true)
    } catch (e) {
      setError(isApiError(e) ? e.message : t('common.error'))
    }
  })

  return (
    <AuthLayout title={t('auth.recoveryTitle')} subtitle={done ? undefined : t('auth.recoverySubtitle')}>
      {done ? (
        <div className="space-y-4">
          <div
            role="status"
            className="flex items-start gap-2 rounded-sm border border-success/30 bg-success-soft p-3 text-body text-success"
          >
            <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" />
            <span className="leading-snug">{t('auth.recoverySent')}</span>
          </div>
          <Button asChild variant="outline" className="h-9 w-full text-body">
            <Link to="/login">{t('auth.backToLogin')}</Link>
          </Button>
        </div>
      ) : (
        <form onSubmit={(e) => void onSubmit(e)} className="space-y-4" noValidate>
          <FormError message={error} />
          <Field id="email" label={t('auth.emailLabel')} error={form.formState.errors.email?.message}>
            <Input id="email" type="email" autoComplete="email" autoFocus {...form.register('email')} />
          </Field>
          <Submit pending={form.formState.isSubmitting}>{t('auth.sendLink')}</Submit>
          <p className="pt-1 text-center text-body text-muted-foreground">
            <Link to="/login" className="text-body text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
              {t('auth.backToLogin')}
            </Link>
          </p>
        </form>
      )}
    </AuthLayout>
  )
}

export function RecoveryConfirmPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const search = useSearch({ from: '/recovery/confirm' })
  const [error, setError] = useState<string | null>(null)
  const schema = z
    .object({
      password: z.string().min(8, t('validation.minLength', { count: 8 })),
      confirm: z.string(),
    })
    .refine((v) => v.password === v.confirm, { path: ['confirm'], message: t('validation.passwordMismatch') })
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { password: '', confirm: '' },
  })

  const onSubmit = form.handleSubmit(async (v) => {
    setError(null)
    try {
      await api.confirmRecovery({ login: search.login ?? '', token: search.token ?? '', password: v.password })
      await navigate({ to: '/login' })
    } catch (e) {
      setError(isApiError(e) ? e.message : t('common.error'))
    }
  })

  return (
    <AuthLayout title={t('auth.resetTitle')} subtitle={t('auth.resetSubtitle')}>
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-4" noValidate>
        <FormError message={error} />
        <Field id="password" label={t('auth.newPassword')} error={form.formState.errors.password?.message}>
          <PasswordInput
            id="password"
            autoComplete="new-password"
            autoFocus
            error={Boolean(form.formState.errors.password)}
            {...form.register('password')}
          />
        </Field>
        <Field id="confirm" label={t('fields.passwordConfirm')} error={form.formState.errors.confirm?.message}>
          <PasswordInput
            id="confirm"
            autoComplete="new-password"
            error={Boolean(form.formState.errors.confirm)}
            {...form.register('confirm')}
          />
        </Field>
        <Submit pending={form.formState.isSubmitting}>{t('auth.resetPassword')}</Submit>
      </form>
    </AuthLayout>
  )
}

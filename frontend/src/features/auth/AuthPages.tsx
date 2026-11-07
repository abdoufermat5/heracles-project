import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useRouter, useSearch } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { z } from 'zod'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import { qk, useDirectories } from '@/api/hooks'
import type { SecondFactorMethod } from '@/api/types'
import { Logo } from '@/components/Logo'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

function AuthLayout({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm space-y-6">
        <Logo className="justify-center" />
        <div className="bg-card space-y-5 rounded-xl border p-6 shadow-sm">
          <div className="space-y-1">
            <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
            {subtitle && <p className="text-muted-foreground text-sm">{subtitle}</p>}
          </div>
          {children}
        </div>
      </div>
    </div>
  )
}

function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
    </div>
  )
}

function FormError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p role="alert" className="bg-destructive/10 text-destructive rounded-md px-3 py-2 text-sm">
      {message}
    </p>
  )
}

function Submit({ pending, children }: { pending: boolean; children: React.ReactNode }) {
  return (
    <Button type="submit" className="w-full" disabled={pending}>
      {pending && <Loader2 className="size-4 animate-spin" aria-hidden />}
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
  const directory = form.watch('directory') || dirs.data?.[0]?.id || ''

  const onSubmit = form.handleSubmit(async (v) => {
    setError(null)
    try {
      const res = await api.login({ ...v, directory: v.directory || directory })
      if (res.status === 'second_factor') {
        await navigate({
          to: '/login/second-factor',
          search: { methods: (res.methods ?? ['totp']).join(','), redirect: search.redirect },
        })
        return
      }
      await qc.invalidateQueries({ queryKey: qk.me })
      if (search.redirect) router.history.push(search.redirect)
      else await navigate({ to: '/' })
    } catch (e) {
      setError(isApiError(e) && e.status !== 401 ? e.message : t('auth.invalidCredentials'))
    }
  })

  return (
    <AuthLayout title={t('auth.loginTitle')} subtitle={t('auth.loginSubtitle')}>
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-4" noValidate>
        <FormError message={error} />
        <Field id="directory" label={t('auth.directory')} error={form.formState.errors.directory?.message}>
          <select
            id="directory"
            {...form.register('directory')}
            value={directory}
            className="border-input bg-background focus-visible:ring-ring/50 h-9 w-full rounded-md border px-3 text-sm shadow-xs outline-none focus-visible:ring-[3px]"
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
          <Input id="password" type="password" autoComplete="current-password" {...form.register('password')} />
        </Field>
        <Submit pending={form.formState.isSubmitting}>{t('auth.signIn')}</Submit>
        <p className="text-center text-sm">
          <Link to="/recovery" className="text-primary hover:underline">
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
    (m): m is SecondFactorMethod => m === 'totp' || m === 'recovery',
  )
  const [method, setMethod] = useState<SecondFactorMethod>(methods[0] ?? 'totp')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!code.trim()) {
      setError(t('validation.required'))
      return
    }
    setPending(true)
    setError(null)
    try {
      await api.secondFactor({ method, code: code.trim() })
      await qc.invalidateQueries({ queryKey: qk.me })
      if (search.redirect) router.history.push(search.redirect)
      else await navigate({ to: '/' })
    } catch (err) {
      setError(isApiError(err) && err.status !== 401 ? err.message : t('auth.invalidCode'))
    } finally {
      setPending(false)
    }
  }

  return (
    <AuthLayout title={t('auth.secondFactorTitle')} subtitle={t(`auth.secondFactorHelp_${method}`)}>
      <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate>
        <FormError message={error} />
        {methods.length > 1 && (
          <div role="group" aria-label={t('auth.method')} className="bg-muted grid grid-cols-2 gap-0.5 rounded-lg p-0.5">
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
                className={
                  method === m
                    ? 'bg-card rounded-md px-3 py-1.5 text-sm font-medium shadow-xs'
                    : 'text-muted-foreground rounded-md px-3 py-1.5 text-sm'
                }
              >
                {t(`auth.method_${m}`)}
              </button>
            ))}
          </div>
        )}
        <Field id="code" label={t(`auth.code_${method}`)}>
          <Input
            id="code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            inputMode={method === 'totp' ? 'numeric' : 'text'}
            autoComplete="one-time-code"
            autoFocus
            className={method === 'totp' ? 'text-center font-mono text-lg tracking-[0.4em]' : 'font-mono'}
            maxLength={method === 'totp' ? 6 : 64}
          />
        </Field>
        <Submit pending={pending}>{t('auth.verify')}</Submit>
        <p className="text-center text-sm">
          <Link to="/login" className="text-primary hover:underline">
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
          <p role="status" className="text-sm">
            {t('auth.recoverySent')}
          </p>
          <Button asChild variant="outline" className="w-full">
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
          <p className="text-center text-sm">
            <Link to="/login" className="text-primary hover:underline">
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
          <Input id="password" type="password" autoComplete="new-password" autoFocus {...form.register('password')} />
        </Field>
        <Field id="confirm" label={t('fields.passwordConfirm')} error={form.formState.errors.confirm?.message}>
          <Input id="confirm" type="password" autoComplete="new-password" {...form.register('confirm')} />
        </Field>
        <Submit pending={form.formState.isSubmitting}>{t('auth.resetPassword')}</Submit>
      </form>
    </AuthLayout>
  )
}

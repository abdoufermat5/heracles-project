import { useQuery } from '@tanstack/react-query'
import { useParams, useSearch } from '@tanstack/react-router'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { AuthLayout } from '@/features/auth/AuthPages'
import { safeLinkHref } from '@/lib/safeUrl'
import { PublicApiError, publicApi, type PublicField, type PublicForm } from './api'
import { useCaptcha } from './useCaptcha'

type Values = Record<string, unknown>

/** Kinds of the field renderer: anything else is shown as a single line of text. */
const INPUT_TYPE: Record<string, string> = {
  email: 'email',
  phone: 'tel',
  url: 'url',
  password: 'password',
  int: 'number',
  float: 'number',
  date: 'date',
}

function Notice({ tone, children }: { tone: 'error' | 'success'; children: React.ReactNode }) {
  const Icon = tone === 'error' ? AlertCircle : CheckCircle2
  const classes =
    tone === 'error'
      ? 'border-destructive/30 bg-destructive-soft text-destructive'
      : 'border-success/30 bg-success-soft text-success'
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={`flex items-start gap-2 rounded-sm border p-2.5 text-body ${classes}`}
    >
      <Icon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span className="leading-snug">{children}</span>
    </div>
  )
}

function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null
  return (
    <p id={`${id}-error`} role="alert" className="mt-1 text-body font-medium text-destructive">
      {message}
    </p>
  )
}

function FieldInput({
  field,
  id,
  value,
  invalid,
  onChange,
}: {
  field: PublicField
  id: string
  value: unknown
  invalid: boolean
  onChange: (v: unknown) => void
}) {
  const disabled = field.readonly
  const common = { id, disabled, 'aria-invalid': invalid || undefined, 'aria-describedby': invalid ? `${id}-error` : undefined }
  const text = typeof value === 'string' || typeof value === 'number' ? String(value) : ''
  if (field.kind === 'boolean') {
    return (
      <div className="flex items-center gap-2">
        <Checkbox {...common} checked={value === true} onCheckedChange={(c) => onChange(c === true)} />
      </div>
    )
  }
  if (field.kind === 'select') {
    return (
      <select
        {...common}
        value={text}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 w-full rounded-md border border-input bg-card px-2.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
      >
        <option value="" />
        {field.options?.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    )
  }
  if (field.kind === 'multiselect') {
    const chosen = Array.isArray(value) ? (value as string[]) : []
    return (
      <div className="space-y-1.5">
        {field.options?.map((o) => (
          <label key={o.value} className="flex items-center gap-2 text-body">
            <Checkbox
              disabled={disabled}
              checked={chosen.includes(o.value)}
              onCheckedChange={(c) => onChange(c === true ? [...chosen, o.value] : chosen.filter((v) => v !== o.value))}
            />
            {o.label}
          </label>
        ))}
      </div>
    )
  }
  if (field.kind === 'text') {
    return <Textarea {...common} rows={4} value={text} onChange={(e) => onChange(e.target.value)} />
  }
  return (
    <Input
      {...common}
      type={INPUT_TYPE[field.kind] ?? 'text'}
      autoComplete={field.kind === 'password' ? 'new-password' : field.kind === 'email' ? 'email' : 'off'}
      value={text}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

/** What goes into `values`: nothing for untouched empty fields, numbers as numbers. */
function toPayload(fields: PublicField[], values: Values): Values {
  const out: Values = {}
  for (const f of fields) {
    if (f.readonly) continue
    const v = values[f.key]
    if (v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0)) continue
    out[f.key] = (f.kind === 'int' || f.kind === 'float') && typeof v === 'string' ? Number(v) : v
  }
  return out
}

function describeFailure(
  e: unknown,
  t: (k: string, o?: Record<string, unknown>) => string,
): string {
  if (!(e instanceof PublicApiError)) return t('publicForms.error.generic')
  if (e.status === 429) {
    const minutes = Math.max(1, Math.ceil((e.retryAfter ?? 60) / 60))
    return t('publicForms.error.rateLimited', { count: minutes })
  }
  if (e.status === 404) return t('publicForms.error.notFound')
  if (e.status === 413) return t('publicForms.error.tooLarge')
  if (e.status === 409) return t('publicForms.error.exists')
  if (e.status === 422) return t('publicForms.error.invalid')
  if (e.status === 0) return t('publicForms.error.network')
  return t('publicForms.error.generic')
}

function FormBody({ form, token }: { form: PublicForm; token?: string }) {
  const { t } = useTranslation()
  const captcha = useCaptcha(form.name, form.captcha)
  const [values, setValues] = useState<Values>(() => Object.fromEntries(form.fields.map((f) => [f.key, f.value ?? ''])))
  const [website, setWebsite] = useState('')
  const [terms, setTerms] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [invitationGone, setInvitationGone] = useState(false)
  const [done, setDone] = useState<string | null>(null)

  const ready = !form.captcha || captcha.answer !== null
  // the terms address is set by whoever edits the form object: only http(s) / same-origin links
  const tosHref = form.tos_url ? safeLinkHref(form.tos_url) : null

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!ready || pending) return
    setPending(true)
    setError(null)
    setFieldErrors({})
    try {
      const res = await publicApi.submit(form.name, {
        values: toPayload(form.fields, values),
        token,
        captcha_token: captcha.answer?.token,
        captcha_answer: captcha.answer?.counter,
        website,
        accept_terms: terms,
      })
      setDone(res.message || form.final_text || '')
    } catch (err) {
      if (err instanceof PublicApiError && err.status === 404 && token) setInvitationGone(true)
      const { captcha_answer: check, ...rest } = err instanceof PublicApiError ? err.fields : ({} as Record<string, string>)
      setFieldErrors(rest)
      setError(check ? t('publicForms.error.check') : describeFailure(err, t))
      captcha.renew() // a challenge is single use
    } finally {
      setPending(false)
    }
  }

  if (invitationGone) return <InvitationGone />
  if (done !== null) {
    return (
      <div className="space-y-4">
        <Notice tone="success">{done || t('publicForms.done')}</Notice>
      </div>
    )
  }

  return (
    <form onSubmit={(e) => void onSubmit(e)} className="relative space-y-4" noValidate>
      {error && <Notice tone="error">{error}</Notice>}
      {form.fields.map((f) => {
        const id = `pf-${f.key.replace(/[^a-zA-Z0-9]/g, '-')}`
        const message = fieldErrors[f.key]
        return (
          <div key={f.key} className="space-y-1.5">
            <Label htmlFor={id} className="text-body font-medium text-foreground">
              {f.label}
              {f.required && !f.readonly && <span aria-hidden> *</span>}
            </Label>
            <FieldInput field={f} id={id} value={values[f.key]} invalid={Boolean(message)} onChange={(v) => setValues((s) => ({ ...s, [f.key]: v }))} />
            {f.description && !message && <p className="text-small text-muted-foreground">{f.description}</p>}
            <FieldError id={id} message={message} />
          </div>
        )
      })}

      {/* Honeypot: invisible and unreachable for people, tempting for scripts. */}
      <div
        aria-hidden="true"
        data-testid="honeypot"
        style={{ position: 'absolute', left: '-10000px', width: 1, height: 1, overflow: 'hidden' }}
      >
        <label>
          Website
          <input
            type="text"
            name="website"
            tabIndex={-1}
            autoComplete="off"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
          />
        </label>
      </div>

      {form.tos_url && (
        <div className="space-y-1.5">
          <label className="flex items-start gap-2 text-body">
            <Checkbox className="mt-0.5" checked={terms} onCheckedChange={(c) => setTerms(c === true)} />
            <span>
              {t('publicForms.acceptTerms')}{' '}
              {tosHref ? (
                <a href={tosHref} target="_blank" rel="noopener noreferrer" className="underline underline-offset-4">
                  {t('publicForms.readTerms')}
                </a>
              ) : (
                t('publicForms.readTerms')
              )}
            </span>
          </label>
          <FieldError id="pf-terms" message={fieldErrors.accept_terms} />
        </div>
      )}

      {form.captcha && captcha.slow && !ready && (
        <p role="status" className="flex items-center gap-2 text-body text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
          {t('publicForms.checking')}
        </p>
      )}

      <Button type="submit" className="h-9 w-full" disabled={!ready || pending}>
        {pending && <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden />}
        {t('publicForms.submit')}
      </Button>
    </form>
  )
}

function InvitationGone() {
  const { t } = useTranslation()
  return (
    <AuthLayout title={t('publicForms.invitationGoneTitle')}>
      <Notice tone="error">{t('publicForms.invitationGone')}</Notice>
    </AuthLayout>
  )
}

/** `/forms/$name[?token=]`: a public form, or the registration page of an invitation link. */
export function PublicFormPage() {
  const { t } = useTranslation()
  const { name } = useParams({ from: '/forms/$name' })
  const { token } = useSearch({ from: '/forms/$name' })
  const query = useQuery({
    queryKey: ['public-form', name, token ?? null],
    queryFn: () => publicApi.form(name, token),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

  if (query.isPending) {
    return (
      <AuthLayout title="">
        <div role="status" aria-label={t('common.loading')} className="flex justify-center py-8">
          <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
        </div>
      </AuthLayout>
    )
  }
  if (query.isError) {
    const e = query.error
    if (e instanceof PublicApiError && e.status === 404 && token) return <InvitationGone />
    return (
      <AuthLayout title={t('publicForms.unavailableTitle')}>
        <Notice tone="error">{describeFailure(e, t)}</Notice>
      </AuthLayout>
    )
  }
  const form = query.data
  if (form.invitation_required) return <InvitationGone />
  return (
    <AuthLayout title={form.title} subtitle={form.text || undefined}>
      <FormBody form={form} token={token} />
    </AuthLayout>
  )
}

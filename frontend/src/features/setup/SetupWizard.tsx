import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Check, CheckCircle2, Copy, Download, Loader2, XCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { isApiError } from '@/api/client'
import type { AttributeDescriptor } from '@/api/types'
import { PasswordField } from '@/components/fields/PasswordField'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { AuthLayout } from '@/features/auth/AuthPages'
import { cn } from '@/lib/utils'
import {
  loadToken,
  saveToken,
  setupApi,
  type AdminInput,
  type ApplyResult,
  type DirectoryInput,
  type DirectoryTestResult,
  type SetupPlugins,
} from './api'

const STEPS = ['welcome', 'directory', 'schema', 'admin', 'plugins', 'review', 'done'] as const
type Step = (typeof STEPS)[number]

const LDIF_COMMAND = 'ldapadd -Y EXTERNAL -H ldapi:/// -f heracles.ldif'

const PASSWORD_DESCRIPTOR = { name: 'userPassword', label: 'Password', kind: 'password' } as AttributeDescriptor

function Field({
  id,
  label,
  help,
  children,
}: {
  id: string
  label: string
  help?: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-body font-medium text-foreground">
        {label}
      </Label>
      {children}
      {help && (
        <p id={`${id}-help`} className="text-small text-muted-foreground">
          {help}
        </p>
      )}
    </div>
  )
}

function Alert({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-sm border border-destructive/30 bg-destructive-soft p-2.5 text-body text-destructive"
    >
      <AlertCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span className="leading-snug">{children}</span>
    </div>
  )
}

function StepNav({
  onBack,
  next,
  nextDisabled,
  busy,
}: {
  onBack?: () => void
  next: string
  nextDisabled?: boolean
  busy?: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-between">
      {onBack ? (
        <Button type="button" variant="ghost" onClick={onBack} disabled={busy}>
          {t('wizard.back')}
        </Button>
      ) : (
        <span />
      )}
      <Button type="submit" disabled={nextDisabled || busy}>
        {busy && <Loader2 className="animate-spin" aria-hidden />}
        {next}
      </Button>
    </div>
  )
}

function Progress({ step }: { step: Step }) {
  const { t } = useTranslation()
  const index = STEPS.indexOf(step)
  return (
    <nav aria-label={t('wizard.title')} className="mb-6">
      <p className="text-small text-muted-foreground sm:hidden">
        {t('wizard.progress', { current: index + 1, total: STEPS.length })} · {t(`wizard.steps.${step}`)}
      </p>
      <ol className="hidden gap-1.5 sm:flex">
        {STEPS.map((s, i) => (
          <li
            key={s}
            aria-current={s === step ? 'step' : undefined}
            className={cn(
              'flex-1 border-t-2 pt-1.5 text-caption',
              i < index && 'border-primary text-foreground',
              i === index && 'border-primary font-medium text-foreground',
              i > index && 'border-border text-muted-foreground',
            )}
          >
            {t(`wizard.steps.${s}`)}
          </li>
        ))}
      </ol>
    </nav>
  )
}

function Heading({ title, help }: { title: string; help?: string }) {
  const ref = useRef<HTMLHeadingElement>(null)
  useEffect(() => ref.current?.focus(), [])
  return (
    <div className="space-y-1.5">
      <h2 ref={ref} tabIndex={-1} className="text-lg font-semibold tracking-tight outline-none">
        {title}
      </h2>
      {help && <p className="text-body text-muted-foreground">{help}</p>}
    </div>
  )
}

// ── Steps ─────────────────────────────────────────────────────────────────

function WelcomeStep({
  version,
  configPath,
  token,
  setToken,
  onVerified,
}: {
  version: string
  configPath: string
  token: string
  setToken: (t: string) => void
  onVerified: () => void
}) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [invalid, setInvalid] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setInvalid(false)
    setFailure(null)
    try {
      await setupApi.verifyToken(token.trim())
      setToken(token.trim())
      onVerified()
    } catch (err) {
      if (isApiError(err) && err.code === 'setup_token_invalid') setInvalid(true)
      else setFailure(isApiError(err) ? err.message : t('wizard.statusError'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate>
      <Heading title={t('wizard.welcome.title')} help={t('wizard.welcome.help')} />
      <p className="rounded-md border bg-muted/40 p-3 text-small text-muted-foreground">
        {t('wizard.welcome.where', { file: '$HERACLES_DATA_DIR/setup-token' })}
      </p>
      {invalid && <Alert>{t('wizard.welcome.invalid')}</Alert>}
      {failure && <Alert>{failure}</Alert>}
      <Field id="setup-token" label={t('wizard.welcome.label')}>
        <Input
          id="setup-token"
          type="password"
          autoComplete="off"
          spellCheck={false}
          autoFocus
          value={token}
          onChange={(e) => {
            setToken(e.target.value)
            setInvalid(false)
          }}
          aria-invalid={invalid || undefined}
          className="font-mono"
        />
      </Field>
      <p className="font-mono text-caption text-muted-foreground">
        {t('wizard.welcome.meta', { version, path: configPath })}
      </p>
      <StepNav next={t('wizard.welcome.verify')} nextDisabled={token.trim() === ''} busy={busy} />
    </form>
  )
}

function ResultRow({ ok, label, detail }: { ok: boolean; label: string; detail?: string }) {
  return (
    <li className="flex items-start gap-2 py-1.5 text-body">
      {ok ? (
        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
      ) : (
        <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
      )}
      <span>
        <span className="font-medium text-foreground">{label}</span>
        <span className="sr-only">{ok ? ': OK' : ': failed'}</span>
        {detail && <span className="block text-small text-muted-foreground">{detail}</span>}
      </span>
    </li>
  )
}

function TestResult({ result }: { result: DirectoryTestResult }) {
  const { t } = useTranslation()
  const failedCode = result.error?.code ?? ''
  const bindFailed = !result.ok && /bind|credential|auth/i.test(failedCode)
  const reachable = result.ok || bindFailed
  return (
    <section aria-label={t('wizard.directory.result')} className="rounded-md border bg-card px-3 py-1.5">
      <ul className="divide-y">
        <ResultRow
          ok={reachable}
          label={t('wizard.directory.rows.reachable')}
          detail={!reachable ? result.error?.message : undefined}
        />
        <ResultRow
          ok={result.ok}
          label={t('wizard.directory.rows.bind')}
          detail={bindFailed ? result.error?.message : undefined}
        />
        {result.ok && (
          <>
            <ResultRow
              ok={result.base_dn_exists}
              label={t('wizard.directory.rows.base')}
              detail={result.base_dn_exists ? undefined : t('wizard.directory.baseMissing')}
            />
            <ResultRow
              ok={result.can_write}
              label={t('wizard.directory.rows.write')}
              detail={result.can_write ? undefined : t('wizard.directory.writeDenied')}
            />
            <ResultRow
              ok={result.schema.installed}
              label={t('wizard.directory.rows.schema')}
              detail={
                result.schema.installed ? undefined : result.schema.missing_classes.join(', ') || undefined
              }
            />
          </>
        )}
      </ul>
    </section>
  )
}

function DirectoryStep({
  token,
  value,
  onChange,
  result,
  setResult,
  onBack,
  onNext,
}: {
  token: string
  value: DirectoryInput
  onChange: (d: DirectoryInput) => void
  result: DirectoryTestResult | null
  setResult: (r: DirectoryTestResult | null) => void
  onBack: () => void
  onNext: () => void
}) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const set = (patch: Partial<DirectoryInput>) => {
    onChange({ ...value, ...patch })
    setResult(null)
  }
  const canTest = value.uri.trim() !== '' && value.bind_dn.trim() !== '' && value.bind_password !== ''
  const passed = result !== null && result.ok && result.base_dn_exists && result.can_write

  const runTest = async (d: DirectoryInput, retry = true) => {
    setBusy(true)
    setFailure(null)
    try {
      const r = await setupApi.testDirectory(token, {
        uri: d.uri.trim(),
        starttls: d.starttls,
        ca_file: d.ca_file?.trim() ? d.ca_file.trim() : null,
        bind_dn: d.bind_dn.trim(),
        bind_password: d.bind_password,
        base_dn: d.base_dn.trim(),
      })
      const suggestion = r.naming_contexts[0]
      if (r.ok && d.base_dn.trim() === '' && suggestion && retry) {
        // first test without a base DN: adopt the server's suggestion and check it right away
        const next = { ...d, base_dn: suggestion }
        onChange(next)
        await runTest(next, false)
        return
      }
      setResult(r)
    } catch (err) {
      setFailure(isApiError(err) ? err.message : t('wizard.statusError'))
    } finally {
      setBusy(false)
    }
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (passed) onNext()
    else if (canTest && !busy) void runTest(value)
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Heading title={t('wizard.directory.title')} help={t('wizard.directory.help')} />
      <Field id="dir-label" label={t('wizard.directory.label')}>
        <Input id="dir-label" value={value.label} onChange={(e) => set({ label: e.target.value })} />
      </Field>
      <Field id="dir-uri" label={t('wizard.directory.uri')} help={t('wizard.directory.uriHelp')}>
        <Input
          id="dir-uri"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          value={value.uri}
          onChange={(e) => set({ uri: e.target.value })}
          aria-describedby="dir-uri-help"
          className="font-mono"
        />
      </Field>
      <div className="flex items-center gap-2">
        <Switch
          id="dir-starttls"
          checked={value.starttls}
          onCheckedChange={(v) => set({ starttls: v })}
          aria-label={t('wizard.directory.starttls')}
        />
        <Label htmlFor="dir-starttls" className="text-body">
          {t('wizard.directory.starttls')}
        </Label>
      </div>
      <Field id="dir-ca" label={t('wizard.directory.caFile')} help={t('wizard.directory.caFileHelp')}>
        <Input
          id="dir-ca"
          autoComplete="off"
          value={value.ca_file ?? ''}
          onChange={(e) => set({ ca_file: e.target.value })}
          aria-describedby="dir-ca-help"
          className="font-mono"
        />
      </Field>
      <Field id="dir-binddn" label={t('wizard.directory.bindDn')}>
        <Input
          id="dir-binddn"
          autoComplete="off"
          spellCheck={false}
          value={value.bind_dn}
          onChange={(e) => set({ bind_dn: e.target.value })}
          className="font-mono"
        />
      </Field>
      <Field id="dir-bindpw" label={t('wizard.directory.bindPassword')}>
        <Input
          id="dir-bindpw"
          type="password"
          autoComplete="off"
          value={value.bind_password}
          onChange={(e) => set({ bind_password: e.target.value })}
        />
      </Field>
      <Field id="dir-base" label={t('wizard.directory.baseDn')}>
        <Input
          id="dir-base"
          autoComplete="off"
          spellCheck={false}
          value={value.base_dn}
          onChange={(e) => set({ base_dn: e.target.value })}
          className="font-mono"
        />
        {result && result.naming_contexts.length > 0 && !result.naming_contexts.includes(value.base_dn) && (
          <div className="flex flex-wrap gap-2 pt-1">
            {result.naming_contexts.map((dn) => (
              <Button key={dn} type="button" variant="outline" size="sm" onClick={() => set({ base_dn: dn })}>
                {t('wizard.directory.useSuggestion', { dn })}
              </Button>
            ))}
          </div>
        )}
      </Field>

      {failure && <Alert>{failure}</Alert>}
      <div>
        <Button type="button" variant="outline" disabled={!canTest || busy} onClick={() => void runTest(value)}>
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          {busy ? t('wizard.directory.testing') : t('wizard.directory.test')}
        </Button>
        {!canTest && <p className="mt-1.5 text-small text-muted-foreground">{t('wizard.directory.required')}</p>}
      </div>
      <div aria-live="polite">{result && <TestResult result={result} />}</div>
      {!result && canTest && <p className="text-small text-muted-foreground">{t('wizard.directory.untested')}</p>}
      <StepNav onBack={onBack} next={t('wizard.continue')} nextDisabled={!passed} />
    </form>
  )
}

function SchemaStep({
  token,
  result,
  recheck,
  onBack,
  onNext,
}: {
  token: string
  result: DirectoryTestResult | null
  recheck: () => Promise<void>
  onBack: () => void
  onNext: () => void
}) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const installed = result?.schema.installed ?? false

  const download = async (format: 'ldif' | 'schema') => {
    setFailure(null)
    try {
      await setupApi.downloadSchema(token, format)
    } catch {
      setFailure(t('wizard.schema.downloadFailed'))
    }
  }
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(LDIF_COMMAND)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* the command stays selectable */
    }
  }
  const check = async () => {
    setBusy(true)
    try {
      await recheck()
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (installed) onNext()
      }}
      className="space-y-4"
    >
      <Heading title={t('wizard.schema.title')} />
      {installed ? (
        <p className="flex items-center gap-2 text-body text-foreground">
          <CheckCircle2 className="size-4 text-success" aria-hidden />
          {t('wizard.schema.installed')}
        </p>
      ) : (
        <>
          <p className="text-body text-muted-foreground">{t('wizard.schema.missing')}</p>
          <ul className="flex flex-wrap gap-1.5">
            {(result?.schema.missing_classes ?? []).map((c) => (
              <li key={c} className="rounded-sm bg-muted px-1.5 py-0.5 font-mono text-caption">
                {c}
              </li>
            ))}
          </ul>
          <p className="text-body text-muted-foreground">{t('wizard.schema.help')}</p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => void download('ldif')}>
              <Download aria-hidden />
              {t('wizard.schema.ldif')}
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => void download('schema')}>
              <Download aria-hidden />
              {t('wizard.schema.schemaFile')}
            </Button>
          </div>
          {failure && <Alert>{failure}</Alert>}
          <div className="space-y-1.5">
            <p className="text-small text-muted-foreground">{t('wizard.schema.command')}</p>
            <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-2">
              <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap font-mono text-small">
                {LDIF_COMMAND}
              </code>
              <Button type="button" variant="ghost" size="sm" onClick={() => void copy()}>
                {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                {copied ? t('wizard.schema.copied') : t('wizard.schema.copy')}
              </Button>
            </div>
          </div>
          <Button type="button" variant="outline" onClick={() => void check()} disabled={busy}>
            {busy && <Loader2 className="animate-spin" aria-hidden />}
            {busy ? t('wizard.schema.checking') : t('wizard.schema.check')}
          </Button>
        </>
      )}
      <StepNav onBack={onBack} next={t('wizard.continue')} nextDisabled={!installed} />
    </form>
  )
}

function AdminStep({
  value,
  onChange,
  confirm,
  setConfirm,
  onBack,
  onNext,
}: {
  value: AdminInput
  onChange: (a: AdminInput) => void
  confirm: string
  setConfirm: (c: string) => void
  onBack: () => void
  onNext: () => void
}) {
  const { t } = useTranslation()
  const set = (patch: Partial<AdminInput>) => onChange({ ...value, ...patch })
  const complete =
    value.uid.trim() !== '' &&
    value.given_name.trim() !== '' &&
    value.surname.trim() !== '' &&
    value.mail.trim() !== '' &&
    value.password !== ''
  const short = value.password !== '' && value.password.length < 8
  const mismatch = value.password !== confirm
  const ok = complete && !short && !mismatch

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (ok) onNext()
      }}
      className="space-y-4"
      noValidate
    >
      <Heading title={t('wizard.admin.title')} help={t('wizard.admin.help')} />
      <Field id="adm-uid" label={t('wizard.admin.uid')}>
        <Input
          id="adm-uid"
          autoComplete="username"
          spellCheck={false}
          value={value.uid}
          onChange={(e) => set({ uid: e.target.value })}
          className="font-mono"
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="adm-given" label={t('wizard.admin.givenName')}>
          <Input
            id="adm-given"
            autoComplete="given-name"
            value={value.given_name}
            onChange={(e) => set({ given_name: e.target.value })}
          />
        </Field>
        <Field id="adm-sn" label={t('wizard.admin.surname')}>
          <Input
            id="adm-sn"
            autoComplete="family-name"
            value={value.surname}
            onChange={(e) => set({ surname: e.target.value })}
          />
        </Field>
      </div>
      <Field id="adm-mail" label={t('wizard.admin.mail')}>
        <Input
          id="adm-mail"
          type="email"
          autoComplete="email"
          value={value.mail}
          onChange={(e) => set({ mail: e.target.value })}
        />
      </Field>
      <Field id="adm-password" label={t('wizard.admin.password')}>
        <PasswordField
          p={{
            descriptor: PASSWORD_DESCRIPTOR,
            id: 'adm-password',
            value: value.password === '' ? null : value.password,
            onChange: (v) => set({ password: typeof v === 'string' ? v : '' }),
            confirm,
            onConfirmChange: setConfirm,
            placeholder: '',
          }}
        />
        {short && (
          <p role="alert" className="text-small text-destructive">
            {t('wizard.admin.tooShort')}
          </p>
        )}
      </Field>
      <StepNav onBack={onBack} next={t('wizard.continue')} nextDisabled={!ok} />
    </form>
  )
}

function profileOf(plugins: SetupPlugins | undefined, selected: string[]): 'core' | 'all' | 'custom' {
  const same = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x))
  for (const p of plugins?.profiles ?? []) if (same(p.plugins, selected)) return p.id
  return 'custom'
}

function PluginsStep({
  token,
  selected,
  setSelected,
  onBack,
  onNext,
}: {
  token: string
  selected: string[] | null
  setSelected: (s: string[]) => void
  onBack: () => void
  onNext: () => void
}) {
  const { t } = useTranslation()
  const { data, isError, isPending } = useQuery({
    queryKey: ['setup', 'plugins'],
    queryFn: () => setupApi.plugins(token),
    retry: false,
    staleTime: Infinity,
  })
  useEffect(() => {
    if (data && selected === null) setSelected(data.plugins.filter((p) => p.default).map((p) => p.name))
  }, [data, selected, setSelected])
  const chosen = selected ?? []
  const profile = profileOf(data, chosen)
  const toggle = (name: string, on: boolean) =>
    setSelected(on ? [...chosen, name] : chosen.filter((n) => n !== name))

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (selected !== null) onNext()
      }}
      className="space-y-4"
    >
      <Heading title={t('wizard.plugins.title')} help={t('wizard.plugins.help')} />
      {isError && <Alert>{t('wizard.plugins.loadFailed')}</Alert>}
      {isPending && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label={t('wizard.loading')} />}
      {data && (
        <>
          <fieldset className="space-y-2">
            <legend className="mb-1.5 text-body font-medium">{t('wizard.plugins.profile')}</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {(['core', 'all', 'custom'] as const).map((id) => {
                const available = id === 'custom' || data.profiles.some((p) => p.id === id)
                return (
                  <label
                    key={id}
                    className={cn(
                      'flex cursor-pointer flex-col rounded-md border bg-card p-3 text-body has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring',
                      profile === id && 'border-primary bg-primary-soft/40',
                      (!available || id === 'custom') && 'cursor-default opacity-70',
                    )}
                  >
                    <span className="flex items-center gap-2 font-medium">
                      <input
                        type="radio"
                        name="plugin-profile"
                        value={id}
                        checked={profile === id}
                        disabled={!available || id === 'custom'}
                        onChange={() => {
                          const p = data.profiles.find((x) => x.id === id)
                          if (p) setSelected([...p.plugins])
                        }}
                      />
                      {t(`wizard.plugins.${id}`)}
                    </span>
                    <span className="text-small text-muted-foreground">{t(`wizard.plugins.${id}Help`)}</span>
                  </label>
                )
              })}
            </div>
          </fieldset>
          <ul className="divide-y rounded-md border bg-card">
            {data.plugins.map((p) => (
              <li key={p.name} className="flex items-start gap-3 px-3 py-2.5">
                <Switch
                  id={`plugin-${p.name}`}
                  checked={chosen.includes(p.name)}
                  onCheckedChange={(v) => toggle(p.name, v)}
                  className="mt-0.5"
                  aria-labelledby={`plugin-${p.name}-label`}
                />
                <Label htmlFor={`plugin-${p.name}`} className="flex-1 flex-col items-start gap-0.5">
                  <span id={`plugin-${p.name}-label`} className="text-body font-medium">
                    {p.label} <span className="font-mono text-caption text-muted-foreground">{p.name}</span>
                  </span>
                  <span className="text-small font-normal text-muted-foreground">{p.description}</span>
                </Label>
              </li>
            ))}
          </ul>
        </>
      )}
      <StepNav onBack={onBack} next={t('wizard.continue')} nextDisabled={selected === null} />
    </form>
  )
}

function Summary({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <section className="rounded-md border bg-card">
      <h3 className="border-b px-3 py-2 text-body font-semibold">{title}</h3>
      <dl className="divide-y">
        {rows.map(([k, v]) => (
          <div key={k} className="grid gap-0.5 px-3 py-1.5 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-3">
            <dt className="text-small text-muted-foreground">{k}</dt>
            <dd className="break-all font-mono text-small text-foreground">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function ReviewStep({
  directory,
  admin,
  plugins,
  publicUrl,
  setPublicUrl,
  busy,
  failure,
  onBack,
  onApply,
}: {
  directory: DirectoryInput
  admin: AdminInput
  plugins: string[]
  publicUrl: string
  setPublicUrl: (u: string) => void
  busy: boolean
  failure: string[] | null
  onBack: () => void
  onApply: () => void
}) {
  const { t } = useTranslation()
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!busy) onApply()
      }}
      className="space-y-4"
      noValidate
    >
      <Heading title={t('wizard.review.title')} help={t('wizard.review.help')} />
      <Summary
        title={t('wizard.review.directory')}
        rows={[
          [t('wizard.directory.label'), directory.label],
          [t('wizard.directory.uri'), directory.uri],
          [t('wizard.review.starttls'), directory.starttls ? t('wizard.review.on') : t('wizard.review.off')],
          ...(directory.ca_file ? ([[t('wizard.directory.caFile'), directory.ca_file]] as [string, string][]) : []),
          [t('wizard.directory.bindDn'), directory.bind_dn],
          [t('wizard.directory.baseDn'), directory.base_dn],
        ]}
      />
      <Summary
        title={t('wizard.review.admin')}
        rows={[
          [t('wizard.admin.uid'), admin.uid],
          [`${t('wizard.admin.givenName')} / ${t('wizard.admin.surname')}`, `${admin.given_name} ${admin.surname}`],
          [t('wizard.admin.mail'), admin.mail],
          [t('wizard.review.password'), t('wizard.review.hidden')],
        ]}
      />
      <Summary
        title={t('wizard.review.plugins')}
        rows={[[t('wizard.review.plugins'), plugins.length ? plugins.join(', ') : t('wizard.review.none')]]}
      />
      <Field id="public-url" label={t('wizard.review.publicUrl')} help={t('wizard.review.publicUrlHelp')}>
        <Input
          id="public-url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          value={publicUrl}
          onChange={(e) => setPublicUrl(e.target.value)}
          placeholder="https://heracles.example.org"
          aria-describedby="public-url-help"
          className="font-mono"
        />
      </Field>
      {failure && (
        <Alert>
          <span className="font-medium">{t('wizard.review.failed')}</span>
          {failure.map((m) => (
            <span key={m} className="block">
              {m}
            </span>
          ))}
        </Alert>
      )}
      <StepNav onBack={onBack} next={busy ? t('wizard.review.applying') : t('wizard.review.apply')} busy={busy} />
    </form>
  )
}

function DoneStep({ result }: { result: ApplyResult }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-4">
      <Heading title={t('wizard.done.title')} help={t('wizard.done.help', { path: result.config_path })} />
      <p className="flex items-center gap-2 text-body">
        <CheckCircle2 className="size-4 text-success" aria-hidden />
        {t('wizard.done.next')}
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Button asChild>
          <Link to="/login" search={{ redirect: undefined }}>
            {t('wizard.done.signIn')}
          </Link>
        </Button>
        <Button asChild variant="outline">
          <Link to="/login" search={{ redirect: '/admin/health' }}>
            {t('wizard.done.health')}
          </Link>
        </Button>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────

const EMPTY_DIRECTORY: DirectoryInput = {
  id: 'default',
  label: 'Main directory',
  uri: 'ldap://',
  starttls: false,
  ca_file: null,
  bind_dn: '',
  bind_password: '',
  base_dn: '',
}
const EMPTY_ADMIN: AdminInput = { uid: 'admin', given_name: '', surname: '', mail: '', password: '' }

export function SetupPage() {
  const { t } = useTranslation()
  const status = useQuery({ queryKey: ['setup', 'status'], queryFn: setupApi.status, retry: false, staleTime: 0, refetchOnWindowFocus: false })
  const [step, setStep] = useState<Step>('welcome')
  const [token, setTokenState] = useState(loadToken)
  const [directory, setDirectory] = useState(EMPTY_DIRECTORY)
  const [test, setTest] = useState<DirectoryTestResult | null>(null)
  const [admin, setAdmin] = useState(EMPTY_ADMIN)
  const [confirm, setConfirm] = useState('')
  const [plugins, setPlugins] = useState<string[] | null>(null)
  const [publicUrl, setPublicUrl] = useState('')
  const [applying, setApplying] = useState(false)
  const [applyFailure, setApplyFailure] = useState<string[] | null>(null)
  const [applied, setApplied] = useState<ApplyResult | null>(null)

  const setToken = (v: string) => {
    setTokenState(v)
    saveToken(v)
  }

  const recheck = async () => {
    const r = await setupApi.testDirectory(token, {
      uri: directory.uri.trim(),
      starttls: directory.starttls,
      ca_file: directory.ca_file?.trim() ? directory.ca_file.trim() : null,
      bind_dn: directory.bind_dn.trim(),
      bind_password: directory.bind_password,
      base_dn: directory.base_dn.trim(),
    })
    setTest(r)
  }

  const apply = async () => {
    setApplying(true)
    setApplyFailure(null)
    try {
      const result = await setupApi.apply(token, {
        directory: {
          ...directory,
          uri: directory.uri.trim(),
          ca_file: directory.ca_file?.trim() ? directory.ca_file.trim() : null,
        },
        admin,
        plugins: plugins ?? [],
        public_url: publicUrl.trim() === '' ? null : publicUrl.trim(),
      })
      setToken('')
      setApplied(result)
      setStep('done')
    } catch (err) {
      if (isApiError(err)) {
        const fields = Object.entries(err.fields).map(([k, v]) => `${k}: ${v}`)
        setApplyFailure(fields.length > 0 ? fields : [err.message])
      } else setApplyFailure([t('wizard.statusError')])
    } finally {
      setApplying(false)
    }
  }

  const go = (s: Step) => () => setStep(s)
  let content: React.ReactNode
  if (status.isPending) {
    content = (
      <p className="flex items-center gap-2 text-body text-muted-foreground" role="status">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {t('wizard.loading')}
      </p>
    )
  } else if (status.isError) {
    content = (
      <div className="space-y-3">
        <Alert>{t('wizard.statusError')}</Alert>
        <Button variant="outline" onClick={() => void status.refetch()}>
          {t('common.retry')}
        </Button>
      </div>
    )
  } else if (!status.data.setup_required && step !== 'done') {
    content = (
      <div className="space-y-4">
        <Heading title={t('wizard.alreadyTitle')} help={t('wizard.alreadyHelp')} />
        <Button asChild>
          <Link to="/login" search={{ redirect: undefined }}>
            {t('wizard.signIn')}
          </Link>
        </Button>
      </div>
    )
  } else {
    content = (
      <>
        <Progress step={step} />
        {step === 'welcome' && (
          <WelcomeStep
            version={status.data.version}
            configPath={status.data.config_path}
            token={token}
            setToken={setToken}
            onVerified={go('directory')}
          />
        )}
        {step === 'directory' && (
          <DirectoryStep
            token={token}
            value={directory}
            onChange={setDirectory}
            result={test}
            setResult={setTest}
            onBack={go('welcome')}
            onNext={go('schema')}
          />
        )}
        {step === 'schema' && (
          <SchemaStep
            token={token}
            result={test}
            recheck={recheck}
            onBack={go('directory')}
            onNext={go('admin')}
          />
        )}
        {step === 'admin' && (
          <AdminStep
            value={admin}
            onChange={setAdmin}
            confirm={confirm}
            setConfirm={setConfirm}
            onBack={go('schema')}
            onNext={go('plugins')}
          />
        )}
        {step === 'plugins' && (
          <PluginsStep
            token={token}
            selected={plugins}
            setSelected={setPlugins}
            onBack={go('admin')}
            onNext={go('review')}
          />
        )}
        {step === 'review' && (
          <ReviewStep
            directory={directory}
            admin={admin}
            plugins={plugins ?? []}
            publicUrl={publicUrl}
            setPublicUrl={setPublicUrl}
            busy={applying}
            failure={applyFailure}
            onBack={go('plugins')}
            onApply={() => void apply()}
          />
        )}
        {step === 'done' && applied && <DoneStep result={applied} />}
      </>
    )
  }

  return (
    <AuthLayout title={t('wizard.title')} subtitle={t('wizard.subtitle')} wide>
      {content}
    </AuthLayout>
  )
}

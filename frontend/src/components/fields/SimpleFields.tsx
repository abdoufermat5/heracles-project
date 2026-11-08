import { ExternalLink, Globe, Mail, MapPin, Phone } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { FieldInputProps } from './types'

const nativeSelectClass =
  'h-8 w-full rounded-md border border-input bg-card px-2.5 py-1 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-destructive'

export function TextInputField({
  p,
  type = 'text',
  mono,
  inputMode,
  icon,
}: {
  p: FieldInputProps
  type?: string
  mono?: boolean
  inputMode?: 'text' | 'email' | 'tel' | 'url' | 'numeric' | 'decimal'
  icon?: React.ReactNode
}) {
  const rawValue = typeof p.value === 'string' ? p.value : ''

  return (
    <div className="relative flex w-full items-center">
      {icon && !p.readOnly && (
        <span className="pointer-events-none absolute left-2.5 text-muted-foreground">
          {icon}
        </span>
      )}
      <Input
        id={p.id}
        type={type}
        inputMode={inputMode}
        value={rawValue}
        onChange={(e) => p.onChange(e.target.value === '' ? null : e.target.value)}
        readOnly={p.readOnly}
        disabled={p.readOnly}
        aria-invalid={p.invalid || undefined}
        aria-describedby={p.error ? `${p.id}-error` : undefined}
        className={cn(
          'h-8 text-[13px]',
          icon && !p.readOnly && 'pl-8',
          mono && 'font-dn',
          p.readOnly &&
            'cursor-default border-transparent bg-transparent px-0 py-1 text-[13px] font-normal text-foreground shadow-none select-text disabled:cursor-default disabled:opacity-100',
        )}
        autoComplete="off"
        placeholder={p.readOnly && !rawValue ? '—' : undefined}
      />
      {p.readOnly && type === 'url' && rawValue && (
        <a
          href={rawValue.startsWith('http') ? rawValue : `https://${rawValue}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:text-primary/80 ml-2 inline-flex items-center gap-1 text-xs"
          title={rawValue}
        >
          <ExternalLink className="size-3.5" />
        </a>
      )}
      {p.readOnly && type === 'email' && rawValue && (
        <a
          href={`mailto:${rawValue}`}
          className="text-primary hover:text-primary/80 ml-2 inline-flex items-center gap-1 text-xs"
          title={rawValue}
        >
          <Mail className="size-3.5" />
        </a>
      )}
    </div>
  )
}

export function TextAreaField({
  p,
  rows = 3,
  icon,
}: {
  p: FieldInputProps
  rows?: number
  icon?: React.ReactNode
}) {
  const rawValue = typeof p.value === 'string' ? p.value : ''

  return (
    <div className="relative">
      {icon && !p.readOnly && (
        <span className="pointer-events-none absolute left-2.5 top-2.5 text-muted-foreground">
          {icon}
        </span>
      )}
      <Textarea
        id={p.id}
        rows={p.readOnly ? Math.min(rows, Math.max(1, rawValue.split('\n').length)) : rows}
        value={rawValue}
        onChange={(e) => p.onChange(e.target.value === '' ? null : e.target.value)}
        readOnly={p.readOnly}
        disabled={p.readOnly}
        aria-invalid={p.invalid || undefined}
        aria-describedby={p.error ? `${p.id}-error` : undefined}
        className={cn(
          'text-[13px]',
          icon && !p.readOnly && 'pl-8',
          p.readOnly &&
            'cursor-default resize-none border-transparent bg-transparent px-0 py-1 text-[13px] font-normal text-foreground shadow-none whitespace-pre-wrap select-text disabled:cursor-default disabled:opacity-100',
        )}
        placeholder={p.readOnly && !rawValue ? '—' : undefined}
      />
    </div>
  )
}

export function PostalAddressField({ p }: { p: FieldInputProps }) {
  return <TextAreaField p={p} rows={3} icon={<MapPin className="size-4" />} />
}

export function EmailInputField({ p }: { p: FieldInputProps }) {
  return (
    <TextInputField
      p={p}
      type="email"
      inputMode="email"
      icon={<Mail className="size-3.5" />}
    />
  )
}

export function PhoneInputField({ p }: { p: FieldInputProps }) {
  return (
    <TextInputField
      p={p}
      type="tel"
      inputMode="tel"
      icon={<Phone className="size-3.5" />}
    />
  )
}

export function UrlInputField({ p }: { p: FieldInputProps }) {
  return (
    <TextInputField
      p={p}
      type="url"
      inputMode="url"
      icon={<Globe className="size-3.5" />}
    />
  )
}

export function NumberField({ p, float }: { p: FieldInputProps; float?: boolean }) {
  const c = p.descriptor.constraints
  const numValue = typeof p.value === 'number' ? p.value : null

  return (
    <Input
      id={p.id}
      type={p.readOnly ? 'text' : 'number'}
      inputMode={float ? 'decimal' : 'numeric'}
      step={float ? 'any' : 1}
      min={c?.min}
      max={c?.max}
      value={numValue !== null ? String(numValue) : p.readOnly ? '—' : ''}
      onChange={(e) => {
        const raw = e.target.value
        if (raw === '') return p.onChange(null)
        const n = float ? Number.parseFloat(raw) : Number.parseInt(raw, 10)
        p.onChange(Number.isNaN(n) ? null : n)
      }}
      readOnly={p.readOnly}
      disabled={p.readOnly}
      aria-invalid={p.invalid || undefined}
      aria-describedby={p.error ? `${p.id}-error` : undefined}
      className={cn(
        'h-8 text-[13px]',
        p.readOnly &&
          'cursor-default border-transparent bg-transparent px-0 py-1 text-[13px] font-normal text-foreground shadow-none select-text disabled:cursor-default disabled:opacity-100',
      )}
    />
  )
}

export function BooleanField({ p }: { p: FieldInputProps }) {
  const checked = p.value === true
  return (
    <div className="flex h-8 items-center gap-3">
      <Switch
        id={p.id}
        checked={checked}
        onCheckedChange={(v) => p.onChange(v)}
        disabled={p.readOnly}
        aria-describedby={p.error ? `${p.id}-error` : undefined}
      />
      <span className={cn('text-[13px]', checked ? 'font-medium text-foreground' : 'text-muted-foreground')}>
        {checked ? 'Yes' : 'No'}
      </span>
    </div>
  )
}

export function SelectField({ p }: { p: FieldInputProps }) {
  const { t } = useTranslation()
  const current = typeof p.value === 'string' ? p.value : ''

  return (
    <select
      id={p.id}
      className={cn(
        nativeSelectClass,
        p.readOnly &&
          'pointer-events-none cursor-default appearance-none border-transparent bg-transparent px-0 py-1 text-[13px] font-normal text-foreground shadow-none select-text disabled:cursor-default disabled:opacity-100',
      )}
      value={current}
      onChange={(e) => p.onChange(e.target.value === '' ? null : e.target.value)}
      disabled={p.readOnly}
      aria-invalid={p.invalid || undefined}
      aria-describedby={p.error ? `${p.id}-error` : undefined}
    >
      {(!p.descriptor.required || current === '') && (
        <option value="">{p.readOnly ? '—' : t('fields.selectPlaceholder')}</option>
      )}
      {(p.descriptor.options ?? []).map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

export function MultiSelectField({ p }: { p: FieldInputProps }) {
  const selected = Array.isArray(p.value) ? (p.value as string[]) : []

  return (
    <div
      role="group"
      aria-labelledby={`${p.id}-label`}
      id={p.id}
      className="flex flex-wrap gap-2 pt-1"
    >
      {(p.descriptor.options ?? []).map((o) => {
        const checked = selected.includes(o.value)
        const cid = `${p.id}-${o.value}`
        return (
          <label
            key={o.value}
            htmlFor={cid}
            className={cn(
              'flex h-6 cursor-pointer items-center gap-2 rounded-sm border px-2 text-xs transition-colors',
              checked
                ? 'border-primary bg-primary-soft text-foreground font-medium'
                : 'border-border hover:bg-accent text-muted-foreground',
              p.readOnly && 'cursor-default border-transparent bg-secondary px-2',
            )}
          >
            <Checkbox
              id={cid}
              checked={checked}
              disabled={p.readOnly}
              onCheckedChange={(v) =>
                p.onChange(v === true ? [...selected, o.value] : selected.filter((x) => x !== o.value))
              }
              className={cn(p.readOnly && 'hidden')}
            />
            {o.label}
          </label>
        )
      })}
      {p.readOnly && selected.length === 0 && (
        <span className="text-[13px] text-muted-foreground">—</span>
      )}
    </div>
  )
}

function toLocalInput(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function DateField({ p }: { p: FieldInputProps }) {
  const raw = typeof p.value === 'string' ? p.value : ''

  return (
    <Input
      id={p.id}
      type={p.readOnly ? 'text' : 'date'}
      value={raw ? raw.slice(0, 10) : p.readOnly ? '—' : ''}
      onChange={(e) => p.onChange(e.target.value || null)}
      readOnly={p.readOnly}
      disabled={p.readOnly}
      aria-invalid={p.invalid || undefined}
      aria-describedby={p.error ? `${p.id}-error` : undefined}
      className={cn(
        'h-8 text-[13px]',
        p.readOnly &&
          'cursor-default border-transparent bg-transparent px-0 py-1 text-[13px] font-normal text-foreground shadow-none select-text disabled:cursor-default disabled:opacity-100',
      )}
    />
  )
}

export function DateTimeField({ p }: { p: FieldInputProps }) {
  const raw = typeof p.value === 'string' ? p.value : ''

  return (
    <Input
      id={p.id}
      type={p.readOnly ? 'text' : 'datetime-local'}
      value={p.readOnly ? (raw ? raw : '—') : toLocalInput(p.value)}
      onChange={(e) => {
        const v = e.target.value
        if (!v) return p.onChange(null)
        const d = new Date(v)
        p.onChange(Number.isNaN(d.getTime()) ? null : d.toISOString())
      }}
      readOnly={p.readOnly}
      disabled={p.readOnly}
      aria-invalid={p.invalid || undefined}
      aria-describedby={p.error ? `${p.id}-error` : undefined}
      className={cn(
        'h-8 text-[13px]',
        p.readOnly &&
          'cursor-default border-transparent bg-transparent px-0 py-1 text-[13px] font-normal text-foreground shadow-none select-text disabled:cursor-default disabled:opacity-100',
      )}
    />
  )
}

export function DisplayField({ p }: { p: FieldInputProps }) {
  const v = p.value
  const text = Array.isArray(v) ? v.join(', ') : v === null || v === undefined || v === '' ? '—' : String(v)
  return (
    <div id={p.id} className="flex min-h-8 items-center text-[13px] font-medium text-foreground">
      {text}
    </div>
  )
}

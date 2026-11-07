import { useTranslation } from 'react-i18next'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { FieldInputProps } from './types'

const nativeSelectClass =
  'border-input bg-background focus-visible:ring-ring/50 h-9 w-full rounded-md border px-3 text-sm shadow-xs outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-destructive'

function describedBy(p: FieldInputProps): string | undefined {
  return p.error ? `${p.id}-error` : undefined
}

export function TextInputField({
  p,
  type = 'text',
  mono,
  inputMode,
}: {
  p: FieldInputProps
  type?: string
  mono?: boolean
  inputMode?: 'text' | 'email' | 'tel' | 'url' | 'numeric' | 'decimal'
}) {
  return (
    <Input
      id={p.id}
      type={type}
      inputMode={inputMode}
      value={typeof p.value === 'string' ? p.value : ''}
      onChange={(e) => p.onChange(e.target.value === '' ? null : e.target.value)}
      readOnly={p.readOnly}
      disabled={p.readOnly}
      aria-invalid={p.invalid || undefined}
      aria-describedby={describedBy(p)}
      className={cn(mono && 'font-dn')}
      autoComplete="off"
    />
  )
}

export function TextAreaField({ p, rows = 3 }: { p: FieldInputProps; rows?: number }) {
  return (
    <Textarea
      id={p.id}
      rows={rows}
      value={typeof p.value === 'string' ? p.value : ''}
      onChange={(e) => p.onChange(e.target.value === '' ? null : e.target.value)}
      disabled={p.readOnly}
      aria-invalid={p.invalid || undefined}
      aria-describedby={describedBy(p)}
    />
  )
}

export function NumberField({ p, float }: { p: FieldInputProps; float?: boolean }) {
  const c = p.descriptor.constraints
  return (
    <Input
      id={p.id}
      type="number"
      inputMode={float ? 'decimal' : 'numeric'}
      step={float ? 'any' : 1}
      min={c?.min}
      max={c?.max}
      value={typeof p.value === 'number' ? String(p.value) : ''}
      onChange={(e) => {
        const raw = e.target.value
        if (raw === '') return p.onChange(null)
        const n = float ? Number.parseFloat(raw) : Number.parseInt(raw, 10)
        p.onChange(Number.isNaN(n) ? null : n)
      }}
      disabled={p.readOnly}
      aria-invalid={p.invalid || undefined}
      aria-describedby={describedBy(p)}
    />
  )
}

export function BooleanField({ p }: { p: FieldInputProps }) {
  return (
    <Switch
      id={p.id}
      checked={p.value === true}
      onCheckedChange={(v) => p.onChange(v)}
      disabled={p.readOnly}
      aria-describedby={describedBy(p)}
    />
  )
}

export function SelectField({ p }: { p: FieldInputProps }) {
  const { t } = useTranslation()
  const current = typeof p.value === 'string' ? p.value : ''
  return (
    <select
      id={p.id}
      className={nativeSelectClass}
      value={current}
      onChange={(e) => p.onChange(e.target.value === '' ? null : e.target.value)}
      disabled={p.readOnly}
      aria-invalid={p.invalid || undefined}
      aria-describedby={describedBy(p)}
    >
      {(!p.descriptor.required || current === '') && <option value="">{t('fields.selectPlaceholder')}</option>}
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
      className="flex flex-wrap gap-2"
    >
      {(p.descriptor.options ?? []).map((o) => {
        const checked = selected.includes(o.value)
        const cid = `${p.id}-${o.value}`
        return (
          <label
            key={o.value}
            htmlFor={cid}
            className={cn(
              'flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm',
              checked && 'border-primary bg-primary-soft',
              p.readOnly && 'cursor-not-allowed opacity-70',
            )}
          >
            <Checkbox
              id={cid}
              checked={checked}
              disabled={p.readOnly}
              onCheckedChange={(v) =>
                p.onChange(v === true ? [...selected, o.value] : selected.filter((x) => x !== o.value))
              }
            />
            {o.label}
          </label>
        )
      })}
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
  return (
    <Input
      id={p.id}
      type="date"
      value={typeof p.value === 'string' ? p.value.slice(0, 10) : ''}
      onChange={(e) => p.onChange(e.target.value || null)}
      disabled={p.readOnly}
      aria-invalid={p.invalid || undefined}
      aria-describedby={describedBy(p)}
    />
  )
}

export function DateTimeField({ p }: { p: FieldInputProps }) {
  return (
    <Input
      id={p.id}
      type="datetime-local"
      value={toLocalInput(p.value)}
      onChange={(e) => {
        const v = e.target.value
        if (!v) return p.onChange(null)
        const d = new Date(v)
        p.onChange(Number.isNaN(d.getTime()) ? null : d.toISOString())
      }}
      disabled={p.readOnly}
      aria-invalid={p.invalid || undefined}
      aria-describedby={describedBy(p)}
    />
  )
}

export function DisplayField({ p }: { p: FieldInputProps }) {
  const v = p.value
  const text = Array.isArray(v) ? v.join(', ') : v === null || v === undefined || v === '' ? '—' : String(v)
  return (
    <div id={p.id} className="text-foreground min-h-9 py-2 text-sm">
      {text}
    </div>
  )
}

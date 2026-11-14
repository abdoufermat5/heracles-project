/* eslint-disable react-refresh/only-export-components -- the hook and its message components belong together */
/**
 * Live validation for the account and access forms.
 *
 * A form describes its rules as a pure `validate(values) -> { field: message }`. The hook
 * decides *when* a message is shown: after the field was left once (or after a save attempt),
 * then on every change. Messages the server sent back for the same fields (422 `fields`) go
 * through the same slots and disappear as soon as the user edits that field.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

export type FieldErrors = Record<string, string>

export interface LiveForm {
  /** Every client-side problem, shown or not. */
  errors: FieldErrors
  /** Message to show under `name` now, if any. */
  message: (name: string) => string | undefined
  /** Number of messages shown now (client and server). */
  shown: number
  /** Whether Save must stay blocked: a message is visible. */
  blocked: boolean
  /** `aria-*` and blur handler for the input of `name`. */
  field: (name: string) => {
    'aria-invalid': true | undefined
    'aria-describedby': string | undefined
    onBlur: () => void
  }
  touch: (name: string) => void
  /** Mark every field as visited; true when nothing is invalid (the save may go on). */
  attempt: () => boolean
  /** Forget visits (after a successful save or when the form is reopened). */
  reset: () => void
}

/** Id of the message element of a field, for `aria-describedby`. */
export const errorId = (formId: string, name: string) => `${formId}-${name}-error`

export function useLiveForm<V extends Record<string, unknown>>(
  formId: string,
  values: V,
  validate: (values: V) => FieldErrors,
  server: FieldErrors | undefined = undefined,
): LiveForm {
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set())
  const [attempted, setAttempted] = useState(false)
  // server messages stay while the field still holds the value the server refused
  const [seen, setSeen] = useState<{ server: FieldErrors | undefined; values: V }>({
    server,
    values,
  })
  if (server !== seen.server) setSeen({ server, values })

  const errors = validate(values)
  const message = (name: string): string | undefined => {
    if (attempted || touched.has(name)) {
      const own = errors[name]
      if (own) return own
    }
    const remote = server?.[name]
    if (remote && Object.is(seen.values[name], values[name])) return remote
    return undefined
  }
  const names = new Set([...Object.keys(errors), ...Object.keys(server ?? {})])
  let shown = 0
  for (const name of names) if (message(name)) shown++

  const touch = (name: string) => setTouched((current) => (current.has(name) ? current : new Set(current).add(name)))
  return {
    errors,
    message,
    shown,
    blocked: shown > 0,
    field: (name) => ({
      'aria-invalid': message(name) ? true : undefined,
      'aria-describedby': message(name) ? errorId(formId, name) : undefined,
      onBlur: () => touch(name),
    }),
    touch,
    attempt: () => {
      setAttempted(true)
      return Object.keys(errors).length === 0
    },
    reset: () => {
      setTouched(new Set())
      setAttempted(false)
    },
  }
}

/** The message under a field (nothing rendered while the field is fine). */
export function FieldError({
  formId,
  name,
  form,
  className,
}: {
  formId: string
  name: string
  form: LiveForm
  className?: string
}) {
  const text = form.message(name)
  if (!text) return null
  return (
    <p id={errorId(formId, name)} role="alert" className={cn('text-caption text-destructive', className)}>
      {text}
    </p>
  )
}

/**
 * Props for a Save button while the form is blocked: announced as disabled and dimmed, but
 * still clickable, so that pressing it shows every remaining problem (the handler calls
 * `attempt()` and stops).
 */
export function blockedProps(form: LiveForm): { 'aria-disabled'?: true; className?: string } {
  return form.blocked ? { 'aria-disabled': true, className: 'opacity-60' } : {}
}

/** Says why Save is blocked: how many fields need a correction. */
export function BlockedHint({ form, className }: { form: LiveForm; className?: string }) {
  const { t } = useTranslation()
  if (!form.blocked) return null
  return (
    <p role="status" className={cn('text-caption text-destructive', className)}>
      {t('formGuard.blocked', { count: form.shown })}
    </p>
  )
}

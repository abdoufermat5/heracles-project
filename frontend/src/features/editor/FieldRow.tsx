import { useController, type Control } from 'react-hook-form'
import type { AttributeDescriptor } from '@/api/types'
import { FieldInput } from '@/components/fields/FieldInput'
import { isWide } from '@/components/fields/types'
import { Label } from '@/components/ui/label'
import type { FormValues } from '@/lib/objects'
import { cn } from '@/lib/utils'

interface Props {
  control: Control<FormValues>
  tab: string
  attr: AttributeDescriptor
  readOnly: boolean
}

/** Label + description + control + error for one attribute, bound to the form. */
export function FieldRow({ control, tab, attr, readOnly }: Props) {
  const name = `${tab}.${attr.name}`
  const id = `f-${tab}-${attr.name}`
  const { field, fieldState } = useController({ control, name: name as never })
  const error = fieldState.error
  const message = typeof error?.message === 'string' ? error.message : undefined

  return (
    <div className={cn('space-y-1.5', isWide(attr) && 'md:col-span-2')} data-field={name}>
      <div className="flex items-center justify-between gap-2">
        <Label
          htmlFor={id}
          id={`${id}-label`}
          className="flex items-center gap-1 text-xs font-medium text-muted-foreground"
        >
          <span>{attr.label}</span>
          {attr.required && attr.kind !== 'password' && (
            <span aria-hidden className="font-medium text-destructive">
              *
            </span>
          )}
        </Label>
        {attr.readonly && !readOnly && (
          <span className="font-mono text-micro text-muted-foreground">readonly</span>
        )}
      </div>

      {attr.kind === 'password' ? (
        <PasswordRow
          control={control}
          name={name}
          id={id}
          attr={attr}
          readOnly={readOnly}
          value={field.value}
          onChange={field.onChange}
          error={message}
        />
      ) : (
        <FieldInput
          descriptor={attr}
          id={id}
          value={field.value}
          onChange={field.onChange}
          readOnly={readOnly}
          invalid={!!error}
          error={message}
          errorTree={error}
        />
      )}

      {attr.description && !message && (
        <p className="text-xs leading-normal text-muted-foreground">{attr.description}</p>
      )}

      {message && (
        <p id={`${id}-error`} role="alert" className="text-xs font-medium text-destructive">
          {message}
        </p>
      )}
    </div>
  )
}

function PasswordRow({
  control,
  name,
  id,
  attr,
  readOnly,
  value,
  onChange,
  error,
}: {
  control: Control<FormValues>
  name: string
  id: string
  attr: AttributeDescriptor
  readOnly: boolean
  value: unknown
  onChange: (v: unknown) => void
  error?: string
}) {
  const { field: confirmField } = useController({ control, name: `${name}__confirm` as never })
  const confirmValue = (confirmField.value as string | undefined) ?? ''

  return (
    <FieldInput
      descriptor={attr}
      id={id}
      value={value}
      onChange={onChange}
      readOnly={readOnly}
      invalid={!!error}
      error={error}
      confirm={confirmValue}
      onConfirmChange={confirmField.onChange as (v: string) => void}
    />
  )
}

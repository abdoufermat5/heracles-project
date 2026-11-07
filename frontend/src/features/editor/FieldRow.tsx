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

function usePasswordConfirm({ control, name }: { control: Control<FormValues>; name: string }) {
  const { field } = useController({ control, name: `${name}__confirm` as never })
  return { value: (field.value as string | undefined) ?? '', onChange: field.onChange as (v: string) => void }
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
      <Label htmlFor={id} id={`${id}-label`} className="gap-1">
        {attr.label}
        {attr.required && attr.kind !== 'password' && (
          <span aria-hidden className="text-destructive">
            *
          </span>
        )}
      </Label>
      {attr.kind === 'password' ? (
        <PasswordRow control={control} name={name} id={id} attr={attr} readOnly={readOnly} value={field.value} onChange={field.onChange} error={message} />
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
        <p className="text-muted-foreground text-xs">{attr.description}</p>
      )}
      {message && (
        <p id={`${id}-error`} role="alert" className="text-destructive text-xs">
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
  const conf = usePasswordConfirm({ control, name })
  return (
    <FieldInput
      descriptor={attr}
      id={id}
      value={value}
      onChange={onChange}
      readOnly={readOnly}
      invalid={!!error}
      error={error}
      confirm={conf.value}
      onConfirmChange={conf.onChange}
    />
  )
}

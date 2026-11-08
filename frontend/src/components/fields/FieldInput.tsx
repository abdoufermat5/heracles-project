import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { AttributeDescriptor, Values } from '@/api/types'
import { Button } from '@/components/ui/button'
import { defaultValue } from '@/lib/objects'
import { FileField, ImageField } from './MediaFields'
import { PasswordField } from './PasswordField'
import { DepartmentField, ObjectRefField } from './RefFields'
import {
  BooleanField,
  DateField,
  DateTimeField,
  DisplayField,
  EmailInputField,
  MultiSelectField,
  NumberField,
  PhoneInputField,
  PostalAddressField,
  SelectField,
  TextAreaField,
  TextInputField,
  UrlInputField,
} from './SimpleFields'
import { errorAt, subTree, type FieldInputProps } from './types'

function ListLike({
  p,
  item,
}: {
  p: FieldInputProps
  item: AttributeDescriptor
}) {
  const { t } = useTranslation()
  const items: unknown[] = Array.isArray(p.value) ? (p.value as unknown[]) : []
  const set = (next: unknown[]) => p.onChange(next)
  const move = (i: number, d: -1 | 1) => {
    const j = i + d
    if (j < 0 || j >= items.length) return
    const copy = [...items]
    const a = copy[i]
    const b = copy[j]
    copy[i] = b
    copy[j] = a
    set(copy)
  }

  return (
    <div className="space-y-2" id={p.id} role="group" aria-labelledby={`${p.id}-label`}>
      {items.length === 0 && (
        <p className="text-muted-foreground text-sm">{t('fields.listEmpty')}</p>
      )}
      <ul className="space-y-2">
        {items.map((it, i) => {
          const err = errorAt(p.errorTree, i)
          const itemId = `${p.id}-${i}`
          return (
            <li key={i} className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <FieldInput
                  descriptor={{ ...item, multivalued: false }}
                  value={it}
                  id={itemId}
                  readOnly={p.readOnly}
                  invalid={!!err || !!subTree(p.errorTree, i)}
                  error={err}
                  errorTree={subTree(p.errorTree, i)}
                  onChange={(v) => set(items.map((x, k) => (k === i ? v : x)))}
                />
                {err && (
                  <p id={`${itemId}-error`} role="alert" className="text-destructive mt-1 text-xs">
                    {err}
                  </p>
                )}
              </div>
              {!p.readOnly && (
                <div className="flex shrink-0 gap-0.5 pt-0.5">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                    aria-label={t('fields.moveUp')}
                    title={t('fields.moveUp')}
                  >
                    <ArrowUp className="size-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-8"
                    disabled={i === items.length - 1}
                    onClick={() => move(i, 1)}
                    aria-label={t('fields.moveDown')}
                    title={t('fields.moveDown')}
                  >
                    <ArrowDown className="size-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="text-destructive hover:text-destructive size-8"
                    onClick={() => set(items.filter((_, k) => k !== i))}
                    aria-label={t('fields.removeItem', { name: String(i + 1) })}
                    title={t('fields.removeItem', { name: String(i + 1) })}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {!p.readOnly && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 gap-1.5"
          onClick={() => set([...items, defaultValue({ ...item, multivalued: false })])}
        >
          <Plus className="size-3.5" />
          {t('fields.addItem')}
        </Button>
      )}
    </div>
  )
}

function CompositeField({ p }: { p: FieldInputProps }) {
  const obj: Values =
    typeof p.value === 'object' && p.value !== null && !Array.isArray(p.value)
      ? (p.value as Values)
      : {}
  return (
    <div
      id={p.id}
      role="group"
      aria-labelledby={`${p.id}-label`}
      className="bg-muted/30 grid gap-3 rounded-lg border border-border p-3.5 sm:grid-cols-2"
    >
      {(p.descriptor.fields ?? []).map((f) => {
        const fid = `${p.id}-${f.name}`
        const err = errorAt(p.errorTree, f.name)
        return (
          <div key={f.name} className="space-y-1.5">
            <label htmlFor={fid} id={`${fid}-label`} className="text-xs font-medium text-foreground">
              {f.label}
              {f.required && <span aria-hidden className="text-destructive font-medium"> *</span>}
            </label>
            <FieldInput
              descriptor={f}
              value={obj[f.name]}
              id={fid}
              readOnly={p.readOnly || f.readonly}
              invalid={!!err}
              error={err}
              errorTree={subTree(p.errorTree, f.name)}
              onChange={(v) => p.onChange({ ...obj, [f.name]: v })}
            />
            {err && (
              <p id={`${fid}-error`} role="alert" className="text-destructive text-xs">
                {err}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Renders the right control for an attribute `kind`. */
export function FieldInput(p: FieldInputProps) {
  const a = p.descriptor
  if (a.kind === 'hidden') return null
  if (a.kind === 'list') {
    return a.item ? <ListLike p={p} item={a.item} /> : null
  }
  // multivalued scalar kinds behave like a list of that kind
  if (a.multivalued && a.kind !== 'multiselect' && a.kind !== 'object_ref' && a.kind !== 'display') {
    return <ListLike p={p} item={{ ...a, multivalued: false, required: false }} />
  }
  switch (a.kind) {
    case 'string':
      return <TextInputField p={p} />
    case 'email':
      return <EmailInputField p={p} />
    case 'phone':
      return <PhoneInputField p={p} />
    case 'url':
      return <UrlInputField p={p} />
    case 'text':
      return <TextAreaField p={p} />
    case 'postal_address':
      return <PostalAddressField p={p} />
    case 'int':
      return <NumberField p={p} />
    case 'float':
      return <NumberField p={p} float />
    case 'boolean':
      return <BooleanField p={p} />
    case 'select':
      return <SelectField p={p} />
    case 'multiselect':
      return <MultiSelectField p={p} />
    case 'date':
      return <DateField p={p} />
    case 'datetime':
      return <DateTimeField p={p} />
    case 'image':
      return <ImageField p={p} />
    case 'file':
      return <FileField p={p} />
    case 'password':
      return <PasswordField p={p} />
    case 'object_ref':
      return <ObjectRefField p={p} />
    case 'department':
      return <DepartmentField p={p} />
    case 'display':
      return <DisplayField p={p} />
    case 'composite':
      return <CompositeField p={p} />
  }
}

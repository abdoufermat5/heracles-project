import { Plus, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { AttributeDescriptor, Values } from '@/api/types'
import { FieldInput } from '@/components/fields/FieldInput'
import { errorAt, subTree } from '@/components/fields/types'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { defaultValue } from '@/lib/objects'

/** A multi-valued attribute whose values are records of several fields (DNS records, …). */
export function isCompositeList(a: AttributeDescriptor): boolean {
  const item = a.kind === 'list' ? a.item : a.multivalued ? a : undefined
  return item?.kind === 'composite' && (item.fields?.length ?? 0) > 0
}

interface Props {
  descriptor: AttributeDescriptor
  id: string
  value: unknown
  onChange: (value: unknown) => void
  readOnly?: boolean
  /** RHF error tree of the attribute (per row, per field). */
  errorTree?: unknown
}

/** Compact table of records: one column per sub-field, one row per value. */
export function CompositeTable({ descriptor, id, value, onChange, readOnly = false, errorTree }: Props) {
  const { t } = useTranslation()
  const item: AttributeDescriptor =
    descriptor.kind === 'list' && descriptor.item
      ? descriptor.item
      : { ...descriptor, multivalued: false }
  const fields = item.fields ?? []
  const rows: Values[] = Array.isArray(value)
    ? (value as unknown[]).map((v) =>
        typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Values) : {},
      )
    : []

  const setCell = (index: number, field: string, v: unknown) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, [field]: v } : row)))

  return (
    <div id={id} role="group" aria-labelledby={`${id}-label`} className="space-y-2">
      {rows.length === 0 ? (
        <p className="text-body text-muted-foreground">{t('fields.listEmpty')}</p>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                {fields.map((f) => (
                  <TableHead key={f.name} className="h-8 text-xs font-medium">
                    {f.label}
                    {f.required && !readOnly && (
                      <span aria-hidden className="ml-1 font-medium text-destructive">
                        *
                      </span>
                    )}
                  </TableHead>
                ))}
                {!readOnly && (
                  <TableHead className="w-10">
                    <span className="sr-only">{t('listing.actions')}</span>
                  </TableHead>
                )}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, i) => (
                <TableRow key={i} className="align-top">
                  {fields.map((f) => {
                    const cellId = `${id}-${i}-${f.name}`
                    const err = errorAt(errorTree, i, f.name)
                    return (
                      <TableCell key={f.name} className="px-2 py-1.5">
                        <label htmlFor={cellId} className="sr-only">
                          {f.label} {i + 1}
                        </label>
                        <FieldInput
                          descriptor={{ ...f, required: false }}
                          id={cellId}
                          value={row[f.name]}
                          readOnly={readOnly || f.readonly}
                          invalid={!!err}
                          error={err}
                          errorTree={subTree(errorTree, i, f.name)}
                          onChange={(v) => setCell(i, f.name, v)}
                        />
                        {err && (
                          <p id={`${cellId}-error`} role="alert" className="mt-1 text-xs text-destructive">
                            {err}
                          </p>
                        )}
                      </TableCell>
                    )
                  })}
                  {!readOnly && (
                    <TableCell className="px-1 py-1.5">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="size-7 text-destructive hover:text-destructive"
                        onClick={() => onChange(rows.filter((_, k) => k !== i))}
                        aria-label={t('fields.removeItem', { name: String(i + 1) })}
                        title={t('fields.removeItem', { name: String(i + 1) })}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {!readOnly && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 gap-1.5"
          onClick={() => onChange([...rows, defaultValue(item)])}
        >
          <Plus className="size-3.5" />
          {t('fields.addItem')}
        </Button>
      )}
    </div>
  )
}

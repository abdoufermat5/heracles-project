import { Check, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { AttributeDescriptor, ObjectListItem, TypeDescriptor, Values } from '@/api/types'
import { DepartmentPicker } from '@/components/fields/RefFields'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCopyMove, type CopyMoveResult } from '@/features/editor/api'
import { allAttributes, rdnValue, UNIQUE_ATTRIBUTES } from '@/lib/objects'

export type CopyMoveMode = 'copy' | 'move'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  mode: CopyMoveMode
  type: string
  descriptor: TypeDescriptor | undefined
  items: ObjectListItem[]
}

interface CopyField {
  tab: string
  attr: AttributeDescriptor
}

/**
 * The values a copy needs from the user: the naming attribute plus the required
 * unique attributes (e-mail, ...) of the always-present tabs. The server never copies
 * those, so each copy has to be given its own.
 */
function copyFields(desc: TypeDescriptor | undefined): CopyField[] {
  if (!desc) return []
  const out: CopyField[] = []
  for (const tab of desc.tabs) {
    for (const attr of allAttributes(tab)) {
      const naming = attr.name === desc.main_attr
      const unique = UNIQUE_ATTRIBUTES.has(attr.name.toLowerCase()) && attr.required === true && !tab.optional
      if ((naming || unique) && attr.kind !== 'password' && attr.kind !== 'display') {
        out.push({ tab: tab.name, attr })
      }
    }
  }
  return out.sort((a, b) => Number(b.attr.name === desc.main_attr) - Number(a.attr.name === desc.main_attr))
}

/** Copy or move objects to another department; a copy asks for the new naming value of each. */
export function CopyMoveDialog(props: Props) {
  // Remount for each opening so the state starts clean.
  return props.open ? <Inner {...props} /> : null
}

function Inner({ onOpenChange, mode, type, descriptor, items }: Props) {
  const { t } = useTranslation()
  const run = useCopyMove(type)
  const [base, setBase] = useState<string | null>(null)
  const fields = copyFields(descriptor)
  // `dn|attribute` -> the new value
  const [given, setGiven] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      items.flatMap((i) =>
        fields.filter((f) => f.attr.name === descriptor?.main_attr).map((f) => [`${i.dn}|${f.attr.name}`, `${rdnValue(i.dn)}-copy`]),
      ),
    ),
  )
  const [results, setResults] = useState<CopyMoveResult[] | null>(null)
  const [touched, setTouched] = useState(false)

  const valuesFor = (dn: string): Record<string, Values> => {
    const out: Record<string, Values> = {}
    for (const f of fields) {
      const tab = (out[f.tab] ??= {})
      tab[f.attr.name] = (given[`${dn}|${f.attr.name}`] ?? '').trim()
    }
    return out
  }

  const submit = async () => {
    setTouched(true)
    if (!base) return
    const out = await run.mutateAsync({
      mode,
      base,
      items: items.map((i) => ({
        dn: i.dn,
        values: mode === 'copy' ? valuesFor(i.dn) : {},
      })),
    })
    setResults(out)
  }

  const failed = results?.filter((r) => !r.ok).length ?? 0
  const okCount = (results?.length ?? 0) - failed
  const title = t(mode === 'copy' ? 'copy.copyTitle' : 'copy.moveTitle', { count: items.length })

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="text-lead">{title}</DialogTitle>
          <DialogDescription className="text-body">
            {t(mode === 'copy' ? 'copy.copyHelp' : 'copy.moveHelp')}
          </DialogDescription>
        </DialogHeader>

        {results === null ? (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="copy-destination" className="text-xs font-medium text-muted-foreground">
                {t('copy.destination')}
              </Label>
              <DepartmentPicker id="copy-destination" value={base} onChange={setBase} invalid={touched && !base} />
              {touched && !base && (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {t('copy.destinationRequired')}
                </p>
              )}
            </div>

            {mode === 'copy' && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground">{t('copy.newNameHelp')}</p>
                <ul className="max-h-64 space-y-2 overflow-y-auto pr-1">
                  {items.map((i) => (
                    <li key={i.dn} className="space-y-1.5 rounded-md border p-2.5">
                      <p className="truncate text-xs font-medium text-foreground" title={i.dn}>
                        {rdnValue(i.dn)}
                      </p>
                      {fields.map((f) => {
                        const key = `${i.dn}|${f.attr.name}`
                        return (
                          <div key={key} className="space-y-1">
                            <Label htmlFor={`copy-${key}`} className="text-xs text-muted-foreground">
                              {t('copy.newName', { attr: f.attr.label })}
                            </Label>
                            <Input
                              id={`copy-${key}`}
                              value={given[key] ?? ''}
                              onChange={(e) => setGiven((g) => ({ ...g, [key]: e.target.value }))}
                              className="h-8 text-body"
                            />
                          </div>
                        )
                      })}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <p role="status" className="text-body font-medium text-foreground">
              {failed === 0
                ? t(mode === 'copy' ? 'copy.copied' : 'copy.moved', { count: okCount })
                : t('copy.partial', { ok: okCount, failed })}
            </p>
            <ul className="max-h-64 space-y-1.5 overflow-y-auto text-body">
              {results.map((r) => (
                <li key={r.dn} className="flex items-start gap-2">
                  {r.ok ? (
                    <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />
                  ) : (
                    <X className="mt-0.5 size-3.5 shrink-0 text-destructive" aria-hidden />
                  )}
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-foreground" title={r.dn}>
                      {rdnValue(r.dn)}
                    </span>
                    {r.ok ? (
                      <span className="text-xs text-muted-foreground">{t('copy.result_ok')}</span>
                    ) : (
                      <span className="text-xs text-destructive">
                        {[r.error, ...Object.values(r.fields ?? {})].filter(Boolean).join(' — ')}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <DialogFooter>
          {results === null ? (
            <>
              <Button type="button" variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
                {t('common.cancel')}
              </Button>
              <Button type="button" size="sm" onClick={() => void submit()} disabled={run.isPending}>
                {t(mode === 'copy' ? 'copy.copy' : 'copy.move')}
              </Button>
            </>
          ) : (
            <Button type="button" size="sm" onClick={() => onOpenChange(false)}>
              {t('copy.done')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

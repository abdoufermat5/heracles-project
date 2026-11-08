import { Check, ChevronDown, ChevronRight, Plus, Trash2 } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { DepartmentPicker } from '@/components/fields/RefFields'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useCatalog, useRoleMutations } from '@/features/admin/hooks'
import { hasRight, nextIndex } from '@/features/admin/rights'
import type { AclRole, Catalog } from '@/features/admin/types'
import { useTechnicalDetails } from '@/lib/preferences'
import { cn } from '@/lib/utils'
import {
  ACTIONS,
  ALL_LETTERS,
  addAttribute,
  actionWords,
  groupRows,
  matrixFromTemplates,
  matrixSentences,
  matrixToTemplates,
  removeAttribute,
  renameAttribute,
  rowHas,
  rowHasContent,
  rowSelf,
  setAttributeRight,
  setColumnAction,
  setRowActions,
  toggleAttributeLetter,
  toggleLetter,
  toggleRowAction,
  toggleRowSelf,
  type Matrix,
  type MatrixRow,
  type MatrixTemplate,
} from './rightsModel'

function labelFor(row: MatrixRow, t: (key: string, options?: Record<string, unknown>) => string) {
  if (row.group === 'all') return t('accessUI.summary.everything')
  if (row.wildcard) {
    return t('accessUI.editor.matrix.wildcard', { category: row.groupLabel })
  }
  return row.label || row.key
}

function AttributeExceptions({
  row,
  onChange,
}: {
  row: MatrixRow
  onChange: (row: MatrixRow) => void
}) {
  const { t } = useTranslation()
  const technical = useTechnicalDetails()
  const options = row.attributesMeta
  const available = options.filter((o) => !row.attributes.some((a) => a.name === o.name))
  const inherited = actionWords(row, t)
  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-small font-semibold text-foreground">
          {t('accessUI.editor.matrix.fieldExceptions')}
        </h4>
        <p className="text-caption text-muted-foreground">
          {t('accessUI.editor.matrix.fieldHelp')}
        </p>
      </div>
      {row.attributes.length === 0 ? (
        <p className="text-small text-muted-foreground">{t('accessUI.editor.matrix.noField')}</p>
      ) : (
        <ul className="space-y-2">
          {row.attributes.map((attribute, index) => {
            const id = `${row.key}-attr-${index}`
            const label =
              options.find((o) => o.name === attribute.name)?.label || attribute.name
            return (
              <li key={`${attribute.name}-${index}`} className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                  <Label htmlFor={id} className="text-caption">
                    {t('accessUI.editor.matrix.field')}
                  </Label>
                  <Select
                    value={attribute.name}
                    onValueChange={(name) => onChange(renameAttribute(row, index, name))}
                  >
                    <SelectTrigger id={id} size="sm" className="w-56">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {!options.some((o) => o.name === attribute.name) && (
                        <SelectItem value={attribute.name}>{attribute.name}</SelectItem>
                      )}
                      {options.map((option) => (
                        <SelectItem key={option.name} value={option.name}>
                          {option.label}
                          <span className="text-muted-foreground"> ({option.name})</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <label className="flex h-8 items-center gap-1.5 text-small">
                  <Checkbox
                    checked={hasRight(attribute.rights, 'r')}
                    aria-label={`${label} — ${t('accessUI.action.read')}`}
                    onCheckedChange={(on) =>
                      onChange(setAttributeRight(row, index, 'r', on === true))
                    }
                  />
                  {t('accessUI.action.read')}
                </label>
                <label className="flex h-8 items-center gap-1.5 text-small">
                  <Checkbox
                    checked={hasRight(attribute.rights, 'w')}
                    aria-label={`${label} — ${t('accessUI.action.change')}`}
                    onCheckedChange={(on) =>
                      onChange(setAttributeRight(row, index, 'w', on === true))
                    }
                  />
                  {t('accessUI.action.change')}
                </label>
                {technical && (
                  <span className="font-mono text-caption text-muted-foreground">
                    {attribute.name}
                  </span>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t('accessUI.editor.matrix.removeField', { attribute: label })}
                  onClick={() => onChange(removeAttribute(row, index))}
                >
                  <Trash2 />
                </Button>
              </li>
            )
          })}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Select
          value=""
          disabled={available.length === 0}
          onValueChange={(name) => onChange(addAttribute(row, name))}
        >
          <SelectTrigger
            size="sm"
            className="w-56"
            aria-label={t('accessUI.editor.matrix.addField')}
          >
            <SelectValue placeholder={t('accessUI.editor.matrix.addField')} />
          </SelectTrigger>
          <SelectContent>
            {available.map((option) => (
              <SelectItem key={option.name} value={option.name}>
                {option.label}
                <span className="text-muted-foreground"> ({option.name})</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-caption text-muted-foreground">
          {inherited.length > 0
            ? t('accessUI.editor.matrix.inherited', { actions: inherited.join(', ') })
            : t('accessUI.editor.matrix.inheritedNone')}
        </span>
      </div>
    </div>
  )
}

function AdvancedBlocks({
  rows,
  onChange,
}: {
  rows: MatrixRow[]
  onChange: (row: MatrixRow) => void
}) {
  const { t } = useTranslation()
  const stored = rows
    .filter(rowHasContent)
    .map(
      (row) =>
        `${row.key};${row.rights}${row.attributes
          .map((a) => `#${a.name};${a.rights}`)
          .join('')}`,
    )
    .join(',')
  return (
    <section className="space-y-2 rounded-md border border-dashed p-3">
      <div>
        <h3 className="text-small font-semibold text-foreground">
          {t('accessUI.editor.matrix.raw')}
        </h3>
        <p className="text-caption text-muted-foreground">{t('accessUI.editor.matrix.rawHelp')}</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-caption">
          <thead>
            <tr>
              <th className="py-1 pr-2 text-left font-medium">
                {t('accessUI.editor.matrix.object')}
              </th>
              {ALL_LETTERS.map((letter) => (
                <th
                  key={letter}
                  className="px-1 py-1 text-center font-medium"
                  title={t(`acl.right.${letter}`)}
                >
                  {letter.toUpperCase()}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Fragment key={row.key}>
                <tr className="border-t">
                  <td className="py-1 pr-2 font-mono break-all">{row.key}</td>
                  {ALL_LETTERS.map((letter) => (
                    <td key={letter} className="px-1 text-center">
                      <Checkbox
                        checked={hasRight(row.rights, letter)}
                        aria-label={`${row.key} ${t(`acl.right.${letter}`)}`}
                        onCheckedChange={() => onChange(toggleLetter(row, letter))}
                      />
                    </td>
                  ))}
                </tr>
                {row.attributes.map((attribute, index) => (
                  <tr key={`${row.key}#${attribute.name}`} className="text-muted-foreground">
                    <td className="py-1 pr-2 pl-4 font-mono break-all">
                      {row.key}#{attribute.name}
                    </td>
                    {ALL_LETTERS.map((letter) => (
                      <td key={letter} className="px-1 text-center">
                        <Checkbox
                          checked={hasRight(attribute.rights, letter)}
                          aria-label={`${row.key}#${attribute.name} ${t(`acl.right.${letter}`)}`}
                          onCheckedChange={() =>
                            onChange(toggleAttributeLetter(row, index, letter))
                          }
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <p className="font-mono text-caption break-all text-muted-foreground">{stored || '—'}</p>
    </section>
  )
}

function TemplateMatrix({
  template,
  position,
  count,
  onChange,
  onRemove,
  catalog,
  technical,
}: {
  template: MatrixTemplate
  position: number
  count: number
  onChange: (template: MatrixTemplate) => void
  onRemove: () => void
  catalog: Catalog | undefined
  technical: boolean
}) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState<string[]>([])
  const [advanced, setAdvanced] = useState(false)
  const groups = useMemo(() => groupRows(template.rows, t), [template.rows, t])
  const setRows = (rows: MatrixTemplate['rows']) => onChange({ ...template, rows })
  const setRow = (next: MatrixRow) =>
    setRows(template.rows.map((row) => (row.key === next.key ? next : row)))
  const toggleExpanded = (key: string) =>
    setExpanded((current) =>
      current.includes(key) ? current.filter((k) => k !== key) : [...current, key],
    )

  const columnState = (action: (typeof ACTIONS)[number]) => {
    const on = template.rows.filter((row) => rowHas(row, action)).length
    return on === 0 ? false : on === template.rows.length ? true : 'indeterminate'
  }

  return (
    <section className="rounded-lg border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <Label htmlFor={`template-${position}`} className="label-caps">
            {t('accessUI.editor.priority')}
          </Label>
          <Input
            id={`template-${position}`}
            type="number"
            min={0}
            value={template.index}
            className="h-7 w-16 text-xs"
            aria-label={t('accessUI.editor.priority')}
            onChange={(e) =>
              onChange({ ...template, index: Math.max(0, Number(e.target.value) || 0) })
            }
          />
          <span className="text-caption text-muted-foreground">
            {t('accessUI.editor.template', { index: template.index })}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {technical && (
            <Button
              type="button"
              variant={advanced ? 'secondary' : 'ghost'}
              size="sm"
              aria-pressed={advanced}
              onClick={() => setAdvanced((value) => !value)}
            >
              {advanced ? t('accessUI.editor.advancedHide') : t('accessUI.editor.advanced')}
            </Button>
          )}
          {count > 1 && (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t('accessUI.editor.removeTemplate', { index: template.index })}
              onClick={onRemove}
            >
              <Trash2 />
            </Button>
          )}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-body">
          <thead>
            <tr className="border-b bg-muted/40 text-left">
              <th className="px-3 py-2 font-medium">{t('accessUI.editor.matrix.object')}</th>
              {ACTIONS.map((action) => (
                <th key={action} className="w-12 px-1 py-2 text-center font-medium">
                  <div className="flex flex-col items-center gap-1">
                    <span>{t(`accessUI.action.${action}`)}</span>
                    <Checkbox
                      checked={columnState(action)}
                      aria-label={t('accessUI.editor.matrix.toggleColumn', {
                        action: t(`accessUI.action.${action}`),
                      })}
                      onCheckedChange={(on) =>
                        setRows(setColumnAction(template.rows, action, on === true))
                      }
                    />
                  </div>
                </th>
              ))}
              <th className="w-20 px-1 py-2 text-center font-medium">
                {t('accessUI.editor.matrix.ownEntry')}
              </th>
              <th className="w-20 px-1 py-2 text-center font-medium">
                {t('accessUI.editor.matrix.details')}
              </th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <Fragment key={group.id}>
                <tr className="bg-muted/30">
                  <th
                    colSpan={ACTIONS.length + 3}
                    scope="colgroup"
                    className="px-3 py-1 text-left text-caption font-semibold tracking-wide text-muted-foreground uppercase"
                  >
                    {group.label}
                  </th>
                </tr>
                {group.rows.map((row) => {
                  const label = labelFor(row, t)
                  const granted = ACTIONS.filter((action) => rowHas(row, action)).length
                  const isOpen = expanded.includes(row.key)
                  return (
                    <Fragment key={row.key}>
                      <tr className={cn('border-t', isOpen && 'bg-muted/20')}>
                        <td className="px-3 py-1.5">
                          <div className="flex items-center gap-2">
                            <Checkbox
                              checked={
                                granted === 0 ? false : granted === ACTIONS.length ? true : 'indeterminate'
                              }
                              aria-label={t('accessUI.editor.matrix.toggleRow', { object: label })}
                              onCheckedChange={(on) => setRow(setRowActions(row, on === true))}
                            />
                            <button
                              type="button"
                              className="flex min-w-0 items-center gap-1 text-left"
                              aria-expanded={isOpen}
                              aria-label={t('accessUI.editor.matrix.fieldsOf', { object: label })}
                              onClick={() => toggleExpanded(row.key)}
                            >
                              {isOpen ? (
                                <ChevronDown className="size-3.5 text-muted-foreground" aria-hidden />
                              ) : (
                                <ChevronRight className="size-3.5 text-muted-foreground" aria-hidden />
                              )}
                              <span className="min-w-0">
                                <span className="block truncate font-medium">{label}</span>
                                {technical && (
                                  <span className="block truncate font-mono text-caption text-muted-foreground">
                                    {row.key}
                                  </span>
                                )}
                                {row.group === 'other' && (
                                  <span className="text-caption text-muted-foreground">
                                    {t('accessUI.editor.matrix.notInCatalog')}
                                  </span>
                                )}
                              </span>
                            </button>
                          </div>
                        </td>
                        {ACTIONS.map((action) => (
                          <td key={action} className="px-1 py-1.5 text-center">
                            <Checkbox
                              checked={rowHas(row, action)}
                              aria-label={`${label} — ${t(`accessUI.action.${action}`)}`}
                              onCheckedChange={() => setRow(toggleRowAction(row, action))}
                            />
                          </td>
                        ))}
                        <td className="px-1 py-1.5 text-center">
                          <Switch
                            checked={rowSelf(row)}
                            aria-label={`${t('accessUI.editor.matrix.ownEntry')}: ${label}`}
                            onCheckedChange={() => setRow(toggleRowSelf(row))}
                          />
                        </td>
                        <td className="px-1 py-1.5 text-center">
                          <Button
                            type="button"
                            variant={row.attributes.length > 0 ? 'secondary' : 'ghost'}
                            size="xs"
                            aria-label={t('accessUI.editor.matrix.openFields', { object: label })}
                            onClick={() => toggleExpanded(row.key)}
                          >
                            {row.attributes.length > 0 ? row.attributes.length : '—'}
                          </Button>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="border-t bg-muted/20">
                          <td colSpan={ACTIONS.length + 3} className="px-4 py-3">
                            <AttributeExceptions row={row} onChange={setRow} />
                            {rowSelf(row) && (
                              <p className="mt-2 text-caption text-muted-foreground">
                                {t('accessUI.editor.matrix.ownEntryHelp')}
                              </p>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {template.rows.length === 0 && (
        <p className="px-3 py-4 text-small text-muted-foreground">
          {catalog ? t('accessUI.editor.matrix.emptyGroup') : t('accessUI.editor.noObjects')}
        </p>
      )}
      {advanced && (
        <div className="border-t p-3">
          <AdvancedBlocks rows={template.rows} onChange={setRow} />
        </div>
      )}
    </section>
  )
}

function RoleSummary({ matrix }: { matrix: Matrix }) {
  const { t } = useTranslation()
  const sentences = useMemo(() => matrixSentences(matrix, t), [matrix, t])
  const objects = new Set(
    matrix.templates.flatMap((template) =>
      template.rows.filter(rowHasContent).map((row) => row.key),
    ),
  )
  return (
    <aside
      aria-label={t('accessUI.editor.summaryTitle')}
      className="space-y-3 rounded-lg border bg-muted/30 p-4"
    >
      <div>
        <h2 className="text-body font-semibold text-foreground">
          {t('accessUI.editor.summaryTitle')}
        </h2>
        <p className="text-caption text-muted-foreground">
          {t('accessUI.roles.objects', { count: objects.size })}
        </p>
      </div>
      {sentences.length === 0 ? (
        <div className="space-y-1">
          <p className="text-body font-medium text-foreground">
            {t('accessUI.editor.summaryEmpty')}
          </p>
          <p className="text-small text-muted-foreground">
            {t('accessUI.editor.summaryEmptyHelp')}
          </p>
        </div>
      ) : (
        <ul className="space-y-1.5">
          {sentences.map((sentence) => (
            <li key={sentence} className="flex gap-1.5 text-small">
              <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden />
              <span>{sentence}</span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}

interface RoleEditorProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** `null` creates a new role. */
  role: AclRole | null
  /** Start a new role from this one. */
  duplicate?: AclRole | null
}

function editorTitle(
  role: AclRole | null,
  duplicate: AclRole | null | undefined,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (role) return t('accessUI.editor.titleEdit', { name: role.cn })
  if (duplicate) return t('accessUI.editor.titleDuplicate', { name: duplicate.cn })
  return t('accessUI.editor.titleNew')
}

/**
 * Wait for the object catalog before building the matrix: rows are catalog
 * objects, and mounting the form early would lose them.
 */
export function RoleEditor(props: RoleEditorProps) {
  const { t } = useTranslation()
  const { data: catalog, isPending } = useCatalog()
  if (isPending) {
    return (
      <Dialog open={props.open} onOpenChange={props.onOpenChange}>
        <DialogContent className="sm:max-w-6xl">
          <DialogHeader>
            <DialogTitle>{editorTitle(props.role, props.duplicate, t)}</DialogTitle>
            <DialogDescription>{t('accessUI.editor.help')}</DialogDescription>
          </DialogHeader>
          <Skeleton className="h-64 w-full" />
        </DialogContent>
      </Dialog>
    )
  }
  return <RoleEditorBody {...props} catalog={catalog} />
}

function RoleEditorBody({
  open,
  onOpenChange,
  role,
  duplicate,
  catalog,
}: RoleEditorProps & { catalog: Catalog | undefined }) {
  const { t } = useTranslation()
  const technical = useTechnicalDetails()
  const { create, update } = useRoleMutations()
  const initial = duplicate ?? role
  const sourceTemplates = initial?.templates ?? [{ index: 0, blocks: [] }]
  const [cn, setCn] = useState(
    role?.cn ?? (duplicate ? t('accessUI.roles.copyName', { name: duplicate.cn }) : ''),
  )
  const [description, setDescription] = useState(
    role?.description ?? duplicate?.description ?? '',
  )
  const [base, setBase] = useState<string | null>(null)
  const [matrix, setMatrix] = useState<Matrix>(() =>
    matrixFromTemplates(sourceTemplates, catalog),
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const busy = create.isPending || update.isPending

  const updateTemplate = (position: number, template: MatrixTemplate) =>
    setMatrix((current) => ({
      ...current,
      templates: current.templates.map((item, i) => (i === position ? template : item)),
    }))

  const submit = async () => {
    setErrors({})
    const sources = role?.templates ?? initial?.templates ?? []
    const templates = matrixToTemplates(matrix, sources)
    try {
      if (role) {
        await update.mutateAsync({ dn: role.dn, description, templates })
      } else {
        await create.mutateAsync({ base, cn: cn.trim(), description, templates })
      }
      toast.success(t('accessUI.roles.saved'))
      onOpenChange(false)
    } catch (e) {
      if (isApiError(e) && e.fields && Object.keys(e.fields).length > 0) setErrors(e.fields)
      else toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[92vh] flex-col overflow-hidden sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>{editorTitle(role, duplicate, t)}</DialogTitle>
          <DialogDescription>{t('accessUI.editor.help')}</DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          <div className="grid gap-3 border-b pb-4 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="role-name">{t('accessUI.editor.name')}</Label>
              <Input
                id="role-name"
                value={cn}
                disabled={role !== null}
                aria-invalid={!!errors.cn}
                onChange={(e) => setCn(e.target.value)}
              />
              {errors.cn && <p className="text-caption text-destructive">{errors.cn}</p>}
            </div>
            {!role && (
              <div className="space-y-1">
                <Label htmlFor="role-base">{t('accessUI.editor.where')}</Label>
                <DepartmentPicker id="role-base" value={base} onChange={setBase} />
                {errors.base && <p className="text-caption text-destructive">{errors.base}</p>}
              </div>
            )}
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="role-description">{t('accessUI.editor.description')}</Label>
              <Textarea
                id="role-description"
                rows={2}
                value={description}
                placeholder={t('accessUI.editor.descriptionPlaceholder')}
                aria-invalid={!!errors.description}
                onChange={(e) => setDescription(e.target.value)}
              />
              {errors.description && (
                <p className="text-caption text-destructive">{errors.description}</p>
              )}
            </div>
          </div>

          <div className="grid gap-4 pt-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <div className="min-w-0 space-y-3">
              {matrix.templates.map((template, position) => (
                <TemplateMatrix
                  key={position}
                  template={template}
                  position={position}
                  count={matrix.templates.length}
                  catalog={catalog}
                  technical={technical}
                  onChange={(next) => updateTemplate(position, next)}
                  onRemove={() =>
                    setMatrix((current) => ({
                      ...current,
                      templates: current.templates.filter((_, i) => i !== position),
                    }))
                  }
                />
              ))}
              <p className="text-caption text-muted-foreground">{t('accessUI.editor.templateHelp')}</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setMatrix((current) => ({
                    ...current,
                    templates: [
                      ...current.templates,
                      { index: nextIndex(current.templates), rows: [] },
                    ],
                  }))
                }
              >
                <Plus />
                {t('accessUI.editor.addTemplate')}
              </Button>
              {Object.entries(errors)
                .filter(([key]) => key.startsWith('templates'))
                .map(([key, value]) => (
                  <p key={key} role="alert" className="text-caption text-destructive">
                    {value}
                  </p>
                ))}
            </div>
            <RoleSummary matrix={matrix} />
          </div>
        </div>

        <DialogFooter className="border-t pt-3">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button
            type="button"
            disabled={busy || (!role && cn.trim() === '')}
            onClick={() => void submit()}
          >
            {role ? t('common.save') : t('common.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

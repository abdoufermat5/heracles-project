import { ChevronDown, ChevronRight, Plus, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
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
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useCatalog, useRoleMutations } from './hooks'
import { RIGHT_LETTERS, hasRight, nextIndex, toggleRight, type RightLetter } from './rights'
import type { AclRole, AttributeRights, Catalog, RightsBlock, RoleTemplate } from './types'

function emptyTemplate(index: number): RoleTemplate {
  return { index, blocks: [] }
}

function labelOf(catalog: Catalog | undefined, key: string): string | null {
  if (!catalog) return null
  if (key === catalog.all) return null
  for (const c of catalog.categories) {
    if (key === c.wildcard) return null
    const o = c.objects.find((x) => x.key === key)
    if (o) return `${c.label} › ${o.label}`
  }
  return null
}

function RightsBoxes({
  rights,
  name,
  onChange,
  disabled,
}: {
  rights: string
  name: string
  onChange: (next: string) => void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  return (
    <>
      {RIGHT_LETTERS.map((letter) => (
        <td key={letter} className="px-1 py-1 text-center">
          <Checkbox
            checked={hasRight(rights, letter)}
            disabled={disabled}
            aria-label={`${name} — ${t(`acl.right.${letter}`)}`}
            onCheckedChange={() => onChange(toggleRight(rights, letter as RightLetter))}
          />
        </td>
      ))}
    </>
  )
}

function BlockRows({
  block,
  catalog,
  onChange,
  onRemove,
}: {
  block: RightsBlock
  catalog: Catalog | undefined
  onChange: (b: RightsBlock) => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(block.attributes.length > 0)
  const known = useMemo(() => {
    for (const c of catalog?.categories ?? []) {
      const o = c.objects.find((x) => x.key === block.object)
      if (o) return o.attributes
    }
    return []
  }, [catalog, block.object])
  const pretty = labelOf(catalog, block.object)
  const special =
    block.object === catalog?.all
      ? t('acl.allObjects')
      : block.object.endsWith('/0')
        ? t('acl.wholeCategory')
        : null

  const setAttr = (i: number, a: AttributeRights) =>
    onChange({ ...block, attributes: block.attributes.map((x, j) => (j === i ? a : x)) })

  return (
    <>
      <tr className="border-t">
        <td className="py-1 pr-2">
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-expanded={open}
              aria-label={t('acl.toggleAttributes', { object: block.object })}
              onClick={() => setOpen((v) => !v)}
            >
              {open ? <ChevronDown /> : <ChevronRight />}
            </Button>
            <div className="min-w-0">
              <div className="font-mono text-[12px]">{block.object}</div>
              {(pretty ?? special) && (
                <div className="truncate text-[11px] text-muted-foreground">{pretty ?? special}</div>
              )}
            </div>
          </div>
        </td>
        <RightsBoxes
          rights={block.rights}
          name={block.object}
          onChange={(rights) => onChange({ ...block, rights })}
        />
        <td className="px-1 text-right">
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label={t('acl.removeObject', { object: block.object })}
            onClick={onRemove}
          >
            <Trash2 />
          </Button>
        </td>
      </tr>
      {open && (
        <>
          {block.attributes.map((a, i) => (
            <tr key={`${a.name}-${i}`} className="bg-muted/40">
              <td className="py-1 pr-2 pl-8">
                {known.length > 0 ? (
                  <Select value={a.name} onValueChange={(name) => setAttr(i, { ...a, name })}>
                    <SelectTrigger size="sm" className="w-48" aria-label={t('acl.attribute')}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {!known.some((k) => k.name === a.name) && (
                        <SelectItem value={a.name}>{a.name}</SelectItem>
                      )}
                      {known.map((k) => (
                        <SelectItem key={k.name} value={k.name}>
                          {k.label} ({k.name})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    value={a.name}
                    className="h-7 w-48 font-mono text-xs"
                    aria-label={t('acl.attribute')}
                    onChange={(e) => setAttr(i, { ...a, name: e.target.value })}
                  />
                )}
              </td>
              <RightsBoxes
                rights={a.rights}
                name={`${block.object}#${a.name}`}
                onChange={(rights) => setAttr(i, { ...a, rights })}
              />
              <td className="px-1 text-right">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={t('acl.removeAttribute', { attribute: a.name })}
                  onClick={() =>
                    onChange({ ...block, attributes: block.attributes.filter((_, j) => j !== i) })
                  }
                >
                  <Trash2 />
                </Button>
              </td>
            </tr>
          ))}
          <tr className="bg-muted/40">
            <td colSpan={RIGHT_LETTERS.length + 2} className="py-1 pl-8">
              <Button
                type="button"
                variant="ghost"
                size="xs"
                onClick={() =>
                  onChange({
                    ...block,
                    attributes: [
                      ...block.attributes,
                      { name: known.find((k) => !block.attributes.some((a) => a.name === k.name))?.name ?? '', rights: 'r' },
                    ],
                  })
                }
              >
                <Plus />
                {t('acl.addAttribute')}
              </Button>
            </td>
          </tr>
        </>
      )}
    </>
  )
}

function AddObject({
  catalog,
  used,
  onAdd,
}: {
  catalog: Catalog | undefined
  used: string[]
  onAdd: (key: string) => void
}) {
  const { t } = useTranslation()
  return (
    <Select value="" onValueChange={onAdd}>
      <SelectTrigger size="sm" className="w-64" aria-label={t('acl.addObject')}>
        <SelectValue placeholder={t('acl.addObject')} />
      </SelectTrigger>
      <SelectContent>
        {catalog && !used.includes(catalog.all) && (
          <SelectGroup>
            <SelectItem value={catalog.all}>{t('acl.allObjects')}</SelectItem>
          </SelectGroup>
        )}
        {catalog?.categories.map((c) => (
          <SelectGroup key={c.category}>
            <SelectLabel>{c.label}</SelectLabel>
            {!used.includes(c.wildcard) && (
              <SelectItem value={c.wildcard}>
                {c.label} — {t('acl.wholeCategory')}
              </SelectItem>
            )}
            {c.objects
              .filter((o) => !used.includes(o.key))
              .map((o) => (
                <SelectItem key={o.key} value={o.key}>
                  {c.label} › {o.label}
                </SelectItem>
              ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  )
}

function TemplateCard({
  template,
  catalog,
  onChange,
  onRemove,
  canRemove,
}: {
  template: RoleTemplate
  catalog: Catalog | undefined
  onChange: (t: RoleTemplate) => void
  onRemove: () => void
  canRemove: boolean
}) {
  const { t } = useTranslation()
  if (template.ignored) {
    return (
      <div className="rounded-md border border-dashed p-3 text-[13px]">
        <p className="font-medium">{t('acl.unreadableTemplate')}</p>
        <p className="font-mono text-xs break-all text-muted-foreground">{template.raw}</p>
        <p className="text-xs text-muted-foreground">{template.reason}</p>
        <Button type="button" variant="ghost" size="xs" className="mt-1" onClick={onRemove}>
          <Trash2 />
          {t('common.delete')}
        </Button>
      </div>
    )
  }
  const setBlock = (i: number, b: RightsBlock) =>
    onChange({ ...template, blocks: template.blocks.map((x, j) => (j === i ? b : x)) })
  return (
    <div className="rounded-md border">
      <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <Label htmlFor={`tpl-${template.index}`} className="label-caps">
            {t('acl.templateIndex')}
          </Label>
          <Input
            id={`tpl-${template.index}`}
            type="number"
            min={0}
            value={template.index}
            className="h-7 w-16 text-xs"
            onChange={(e) => onChange({ ...template, index: Math.max(0, Number(e.target.value) || 0) })}
          />
        </div>
        <div className="flex items-center gap-1">
          <AddObject
            catalog={catalog}
            used={template.blocks.map((b) => b.object)}
            onAdd={(key) =>
              onChange({ ...template, blocks: [...template.blocks, { object: key, rights: 'r', attributes: [] }] })
            }
          />
          {canRemove && (
            <Button type="button" variant="ghost" size="icon-sm" aria-label={t('acl.removeTemplate')} onClick={onRemove}>
              <Trash2 />
            </Button>
          )}
        </div>
      </div>
      {template.blocks.length === 0 ? (
        <p className="px-3 py-4 text-[13px] text-muted-foreground">{t('acl.noObjects')}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left">
                <th className="label-caps px-3 py-1.5 font-medium">{t('acl.object')}</th>
                {RIGHT_LETTERS.map((l) => (
                  <th key={l} className="label-caps px-1 py-1.5 text-center font-medium" title={t(`acl.right.${l}`)}>
                    {l.toUpperCase()}
                  </th>
                ))}
                <th />
              </tr>
            </thead>
            <tbody className="[&>tr>td:first-child]:px-3">
              {template.blocks.map((b, i) => (
                <BlockRows
                  key={`${b.object}-${i}`}
                  block={b}
                  catalog={catalog}
                  onChange={(nb) => setBlock(i, nb)}
                  onRemove={() => onChange({ ...template, blocks: template.blocks.filter((_, j) => j !== i) })}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function RoleEditor({
  open,
  onOpenChange,
  role,
  readOnly,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  /** `null` creates a new role. */
  role: AclRole | null
  readOnly?: boolean
}) {
  const { t } = useTranslation()
  const { data: catalog } = useCatalog()
  const { create, update } = useRoleMutations()
  const [cn, setCn] = useState(role?.cn ?? '')
  const [description, setDescription] = useState(role?.description ?? '')
  const [base, setBase] = useState<string | null>(null)
  const [templates, setTemplates] = useState<RoleTemplate[]>(
    role?.templates.length ? role.templates : [emptyTemplate(0)],
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const busy = create.isPending || update.isPending

  const submit = async () => {
    setErrors({})
    try {
      if (role) {
        await update.mutateAsync({ dn: role.dn, description, templates })
      } else {
        await create.mutateAsync({ base, cn, description, templates })
      }
      toast.success(t('acl.roleSaved'))
      onOpenChange(false)
    } catch (e) {
      if (isApiError(e) && e.fields && Object.keys(e.fields).length > 0) setErrors(e.fields)
      else toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col overflow-hidden sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{role ? t('acl.editRole', { name: role.cn }) : t('acl.newRole')}</DialogTitle>
          <DialogDescription>{t('acl.roleHelp')}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="role-cn">{t('acl.name')}</Label>
              <Input
                id="role-cn"
                value={cn}
                disabled={role !== null || readOnly}
                aria-invalid={!!errors.cn}
                onChange={(e) => setCn(e.target.value)}
              />
              {errors.cn && <p className="text-xs text-destructive">{errors.cn}</p>}
            </div>
            {!role && (
              <div className="space-y-1">
                <Label htmlFor="role-base">{t('acl.department')}</Label>
                <DepartmentPicker id="role-base" value={base} onChange={setBase} />
              </div>
            )}
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="role-description">{t('acl.description')}</Label>
              <Textarea
                id="role-description"
                rows={2}
                value={description}
                disabled={readOnly}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-3">
            {templates.map((tpl, i) => (
              <TemplateCard
                key={i}
                template={tpl}
                catalog={catalog}
                canRemove={templates.length > 1}
                onChange={(nt) => setTemplates(templates.map((x, j) => (j === i ? nt : x)))}
                onRemove={() => setTemplates(templates.filter((_, j) => j !== i))}
              />
            ))}
            {!readOnly && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setTemplates([...templates, emptyTemplate(nextIndex(templates))])}
              >
                <Plus />
                {t('acl.addTemplate')}
              </Button>
            )}
            {Object.entries(errors)
              .filter(([k]) => k.startsWith('templates'))
              .map(([k, v]) => (
                <p key={k} role="alert" className="text-xs text-destructive">
                  {v}
                </p>
              ))}
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          {!readOnly && (
            <Button type="button" disabled={busy || (!role && cn.trim() === '')} onClick={() => void submit()}>
              {role ? t('common.save') : t('common.create')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

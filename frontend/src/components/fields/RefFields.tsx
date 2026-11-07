import { Check, ChevronDown, ChevronRight, ChevronsUpDown, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useRefSearch, useTree } from '@/api/hooks'
import type { TreeNode } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { rdnValue } from '@/lib/objects'
import { cn } from '@/lib/utils'
import type { FieldInputProps } from './types'

function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

/** Async searchable combobox over `GET /objects/{ref_type}?q=`. */
export function ObjectRefPicker({
  id,
  refType,
  onPick,
  disabled,
  invalid,
  label,
  selected,
}: {
  id: string
  refType: string
  onPick: (dn: string) => void
  disabled?: boolean
  invalid?: boolean
  label: string
  selected: string[]
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const { data, isFetching } = useRefSearch(refType, dq, open)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-invalid={invalid || undefined}
          disabled={disabled}
          className="w-full justify-between font-normal"
        >
          <span className="text-muted-foreground truncate">{label}</span>
          <ChevronsUpDown className="size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) p-0" align="start">
        <Command shouldFilter={false}>
          <div className="border-b p-2">
            <Input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('fields.searchPlaceholder')}
              aria-label={t('fields.searchPlaceholder')}
            />
          </div>
          <CommandList>
            {!isFetching && (data?.items.length ?? 0) === 0 && (
              <CommandEmpty>{t('fields.noResults')}</CommandEmpty>
            )}
            {isFetching && !data && (
              <div className="text-muted-foreground p-3 text-sm">{t('common.loading')}</div>
            )}
            <CommandGroup>
              {data?.items.map((item) => {
                const isSel = selected.includes(item.dn)
                const first = Object.values(item.values).find((v) => typeof v === 'string')
                return (
                  <CommandItem
                    key={item.dn}
                    value={item.dn}
                    onSelect={() => {
                      onPick(item.dn)
                      setOpen(false)
                    }}
                  >
                    <Check className={cn('size-4', isSel ? 'opacity-100' : 'opacity-0')} />
                    <div className="min-w-0">
                      <div className="truncate">{typeof first === 'string' ? first : rdnValue(item.dn)}</div>
                      <div className="font-dn text-muted-foreground truncate text-xs">{item.dn}</div>
                    </div>
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

function Chip({ dn, onRemove, disabled }: { dn: string; onRemove: () => void; disabled?: boolean }) {
  const { t } = useTranslation()
  return (
    <Badge variant="secondary" className="max-w-full gap-1 pr-1 font-normal" title={dn}>
      <span className="truncate">{rdnValue(dn)}</span>
      {!disabled && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={t('fields.removeItem', { name: rdnValue(dn) })}
          className="hover:bg-accent rounded-sm p-0.5"
        >
          <X className="size-3" />
        </button>
      )}
    </Badge>
  )
}

export function ObjectRefField({ p }: { p: FieldInputProps }) {
  const { t } = useTranslation()
  const refType = p.descriptor.ref_type ?? 'user'
  const multi = p.descriptor.multivalued === true
  const values: string[] = multi
    ? Array.isArray(p.value)
      ? (p.value as string[])
      : []
    : typeof p.value === 'string' && p.value
      ? [p.value]
      : []

  return (
    <div className="space-y-2">
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((dn) => (
            <Chip
              key={dn}
              dn={dn}
              disabled={p.readOnly}
              onRemove={() => p.onChange(multi ? values.filter((x) => x !== dn) : null)}
            />
          ))}
        </div>
      )}
      {(!p.readOnly && (multi || values.length === 0)) && (
        <ObjectRefPicker
          id={p.id}
          refType={refType}
          selected={values}
          invalid={p.invalid}
          label={multi ? t('fields.addObject') : t('fields.selectObject')}
          onPick={(dn) => p.onChange(multi ? Array.from(new Set([...values, dn])) : dn)}
        />
      )}
      {p.readOnly && values.length === 0 && <span className="text-muted-foreground">—</span>}
    </div>
  )
}

function findNode(nodes: TreeNode[], dn: string): TreeNode | null {
  for (const n of nodes) {
    if (n.dn.toLowerCase() === dn.toLowerCase()) return n
    const c = findNode(n.children, dn)
    if (c) return c
  }
  return null
}

export function TreeList({
  nodes,
  onSelect,
  selected,
  level = 0,
}: {
  nodes: TreeNode[]
  onSelect: (n: TreeNode) => void
  selected?: string | null
  level?: number
}) {
  return (
    <ul role={level === 0 ? 'tree' : 'group'} className="space-y-0.5">
      {nodes.map((n) => (
        <TreeItem key={n.dn} node={n} onSelect={onSelect} selected={selected} level={level} />
      ))}
    </ul>
  )
}

function TreeItem({
  node,
  onSelect,
  selected,
  level,
}: {
  node: TreeNode
  onSelect: (n: TreeNode) => void
  selected?: string | null
  level: number
}) {
  const [open, setOpen] = useState(level < 1)
  const has = node.children.length > 0
  const isSel = selected?.toLowerCase() === node.dn.toLowerCase()
  return (
    <li role="treeitem" aria-expanded={has ? open : undefined} aria-selected={isSel}>
      <div
        className={cn(
          'hover:bg-accent flex items-center gap-1 rounded-md pr-2',
          isSel && 'bg-primary-soft text-foreground',
        )}
        style={{ paddingLeft: level * 14 }}
      >
        <button
          type="button"
          className="text-muted-foreground flex size-6 items-center justify-center"
          onClick={() => setOpen((o) => !o)}
          tabIndex={has ? 0 : -1}
          aria-label={has ? node.label : undefined}
          aria-hidden={!has}
        >
          {has ? open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" /> : null}
        </button>
        <button
          type="button"
          className="flex-1 truncate py-1.5 text-left text-sm"
          onClick={() => onSelect(node)}
        >
          {node.label}
        </button>
      </div>
      {has && open && <TreeList nodes={node.children} onSelect={onSelect} selected={selected} level={level + 1} />}
    </li>
  )
}

/** Department tree picker. */
export function DepartmentPicker({
  id,
  value,
  onChange,
  disabled,
  invalid,
}: {
  id: string
  value: string | null
  onChange: (dn: string) => void
  disabled?: boolean
  invalid?: boolean
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const { data: tree } = useTree()
  const current = value && tree ? findNode(tree, value) : null
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          aria-invalid={invalid || undefined}
          className="w-full justify-between font-normal"
        >
          <span className={cn('truncate', !value && 'text-muted-foreground')}>
            {current?.label ?? (value ? rdnValue(value) : t('fields.selectDepartment'))}
          </span>
          <ChevronsUpDown className="size-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="max-h-80 w-72 overflow-auto p-2" align="start">
        {tree ? (
          <TreeList
            nodes={tree}
            selected={value}
            onSelect={(n) => {
              onChange(n.dn)
              setOpen(false)
            }}
          />
        ) : (
          <div className="text-muted-foreground p-2 text-sm">{t('common.loading')}</div>
        )}
      </PopoverContent>
    </Popover>
  )
}

export function DepartmentField({ p }: { p: FieldInputProps }) {
  return (
    <DepartmentPicker
      id={p.id}
      value={typeof p.value === 'string' ? p.value : null}
      onChange={(dn) => p.onChange(dn)}
      disabled={p.readOnly}
      invalid={p.invalid}
    />
  )
}

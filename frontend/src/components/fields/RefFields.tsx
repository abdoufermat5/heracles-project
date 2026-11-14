import {
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronsUpDown,
  Search,
  User,
  Users,
  X,
} from 'lucide-react'
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

function getRefIcon(refType: string) {
  switch (refType) {
    case 'group':
      return <Users className="size-3.5 text-muted-foreground shrink-0" />
    case 'department':
      return <Building2 className="size-3.5 text-muted-foreground shrink-0" />
    default:
      return <User className="size-3.5 text-muted-foreground shrink-0" />
  }
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
          className="h-8 w-full justify-between text-body font-normal"
        >
          <span className="text-muted-foreground truncate">{label}</span>
          <ChevronsUpDown className="size-3.5 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) min-w-72 p-0" align="start">
        <Command shouldFilter={false}>
          <div className="flex items-center border-b px-2.5 py-1.5">
            <Search className="size-3.5 text-muted-foreground mr-2 shrink-0" />
            <Input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('fields.searchPlaceholder')}
              aria-label={t('fields.searchPlaceholder')}
              className="h-7 border-0 p-0 text-body shadow-none focus-visible:ring-0"
            />
          </div>
          <CommandList className="max-h-64">
            {!isFetching && (data?.items.length ?? 0) === 0 && (
              <CommandEmpty>{t('fields.noResults')}</CommandEmpty>
            )}
            {isFetching && !data && (
              <div className="text-muted-foreground p-3 text-center text-xs">{t('common.loading')}</div>
            )}
            <CommandGroup>
              {data?.items.map((item) => {
                const isSel = selected.includes(item.dn)
                const first = Object.values(item.values).find((v) => typeof v === 'string')
                const displayName = typeof first === 'string' ? first : rdnValue(item.dn)
                return (
                  <CommandItem
                    key={item.dn}
                    value={item.dn}
                    onSelect={() => {
                      onPick(item.dn)
                      setOpen(false)
                    }}
                    className="flex items-center gap-2 px-2.5 py-2 cursor-pointer"
                  >
                    <Check className={cn('size-3.5 shrink-0', isSel ? 'opacity-100 text-primary' : 'opacity-0')} />
                    {getRefIcon(refType)}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-body font-medium">{displayName}</div>
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

function Chip({
  dn,
  refType,
  onRemove,
  disabled,
}: {
  dn: string
  refType?: string
  onRemove: () => void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const display = rdnValue(dn)
  return (
    <Badge
      variant="secondary"
      className="h-6 max-w-full gap-1 rounded-sm border-border bg-muted px-1.5 py-0 font-normal text-xs text-foreground transition-colors"
      title={dn}
    >
      {refType && getRefIcon(refType)}
      <span className="max-w-[200px] truncate font-mono">{display}</span>
      {!disabled && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={t('fields.removeItem', { name: display })}
          className="hover:bg-accent text-muted-foreground hover:text-foreground rounded-sm p-0.5 transition-colors"
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
        <div className="flex flex-wrap gap-1.5 py-0.5">
          {values.map((dn) => (
            <Chip
              key={dn}
              dn={dn}
              refType={refType}
              disabled={p.readOnly}
              onRemove={() => p.onChange(multi ? values.filter((x) => x !== dn) : null)}
            />
          ))}
        </div>
      )}
      {!p.readOnly && (multi || values.length === 0) && (
        <ObjectRefPicker
          id={p.id}
          refType={refType}
          selected={values}
          invalid={p.invalid}
          label={multi ? t('fields.addObject') : t('fields.selectObject')}
          onPick={(dn) => p.onChange(multi ? Array.from(new Set([...values, dn])) : dn)}
        />
      )}
      {p.readOnly && values.length === 0 && (
        <span className="text-body text-muted-foreground">—</span>
      )}
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

function filterTree(nodes: TreeNode[], term: string): TreeNode[] {
  if (!term) return nodes
  const lower = term.toLowerCase()
  const out: TreeNode[] = []
  for (const n of nodes) {
    const matchesSelf = n.label.toLowerCase().includes(lower) || n.dn.toLowerCase().includes(lower)
    const matchingChildren = filterTree(n.children, term)
    if (matchesSelf || matchingChildren.length > 0) {
      out.push({
        ...n,
        children: matchingChildren,
      })
    }
  }
  return out
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
  const { t } = useTranslation()
  const [open, setOpen] = useState(level < 1)
  // The tree root is the directory base, named by its technical RDN: show the usual name
  const label = level === 0 ? t('patterns.topLevel') : node.label
  const has = node.children.length > 0
  const isSel = selected?.toLowerCase() === node.dn.toLowerCase()
  return (
    <li role="treeitem" aria-expanded={has ? open : undefined} aria-selected={isSel}>
      <div
        className={cn(
          'flex h-7 items-center gap-1 rounded-sm pr-2 transition-colors hover:bg-accent',
          isSel && 'bg-primary-soft font-medium text-foreground',
        )}
        style={{ paddingLeft: level * 14 }}
      >
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground flex size-6 shrink-0 items-center justify-center rounded-sm"
          onClick={() => setOpen((o) => !o)}
          tabIndex={has ? 0 : -1}
          aria-label={has ? label : undefined}
          aria-hidden={!has}
        >
          {has ? open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" /> : null}
        </button>
        <button
          type="button"
          className="flex-1 truncate py-1 text-left text-body"
          onClick={() => onSelect(node)}
          title={node.dn}
        >
          <span className="flex items-center gap-1.5">
            <Building2 className="size-3 text-muted-foreground shrink-0" />
            <span className="truncate">{label}</span>
          </span>
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
  const [search, setSearch] = useState('')
  const { data: tree } = useTree()
  const current = value && tree ? findNode(tree, value) : null
  const currentLabel =
    current && tree?.[0]?.dn === current.dn ? t('patterns.topLevel') : current?.label
  const filteredNodes = tree ? filterTree(tree, search) : []

  if (disabled) {
    return (
      <div id={id} className="flex h-8 items-center gap-1.5 text-body font-medium">
        <Building2 className="size-3.5 text-muted-foreground" />
        <span className="truncate">{currentLabel ?? (value ? rdnValue(value) : '—')}</span>
      </div>
    )
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          disabled={disabled}
          aria-invalid={invalid || undefined}
          className="h-8 w-full justify-between text-body font-normal"
        >
          <span className={cn('flex items-center gap-1.5 truncate', !value && 'text-muted-foreground')}>
            <Building2 className="size-3.5 text-muted-foreground shrink-0" />
            <span className="truncate">{currentLabel ?? (value ? rdnValue(value) : t('fields.selectDepartment'))}</span>
          </span>
          <ChevronsUpDown className="size-3.5 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-2" align="start">
        <div className="mb-2 border-b pb-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-2 size-3.5 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('fields.searchPlaceholder')}
              className="h-7 pl-7 text-xs"
            />
          </div>
        </div>
        <div className="max-h-72 overflow-auto">
          {tree ? (
            filteredNodes.length > 0 ? (
              <TreeList
                nodes={filteredNodes}
                selected={value}
                onSelect={(n) => {
                  onChange(n.dn)
                  setOpen(false)
                  setSearch('')
                }}
              />
            ) : (
              <div className="text-muted-foreground p-3 text-center text-xs">{t('fields.noResults')}</div>
            )
          ) : (
            <div className="text-muted-foreground p-3 text-center text-xs">{t('common.loading')}</div>
          )}
        </div>
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

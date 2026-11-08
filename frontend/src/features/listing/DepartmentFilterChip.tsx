import { Building2, ChevronDown, Search, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useTree } from '@/api/hooks'
import type { TreeNode } from '@/api/types'
import { TreeList } from '@/components/fields/RefFields'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { Scope } from '@/lib/scope'
import { cn } from '@/lib/utils'

function findNode(nodes: TreeNode[], dn: string): TreeNode | null {
  for (const n of nodes) {
    if (n.dn.toLowerCase() === dn.toLowerCase()) return n
    const c = findNode(n.children, dn)
    if (c) return c
  }
  return null
}

function filterTree(nodes: TreeNode[], term: string): TreeNode[] {
  if (!term.trim()) return nodes
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

interface DepartmentFilterChipProps {
  base: string | null
  scope: Scope
  onBaseChange: (base: string | null) => void
  onScopeChange: (scope: Scope) => void
}

export function DepartmentFilterChip({
  base,
  scope,
  onBaseChange,
  onScopeChange,
}: DepartmentFilterChipProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const { data: tree } = useTree()

  const currentNode = base && tree ? findNode(tree, base) : null
  const active = Boolean(base)
  const filteredNodes = tree ? filterTree(tree, search) : []

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={cn(
            'border-dashed',
            active && 'border-solid border-primary/40 bg-primary-soft',
          )}
        >
          <Building2 className="size-3.5 opacity-60" aria-hidden />
          <span>{t('peopleUI.filters.department')}</span>
          {active && (
            <span className="max-w-36 truncate font-normal text-primary">
              {currentNode?.label ?? 'Selected'}
            </span>
          )}
          <ChevronDown className="opacity-60" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-3">
        <div className="flex items-center justify-between pb-2 border-b">
          <span className="text-small font-semibold text-foreground">
            {t('peopleUI.filters.department')}
          </span>
          {active && (
            <button
              type="button"
              onClick={() => {
                onBaseChange(null)
                setOpen(false)
              }}
              className="text-caption text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              <X className="size-3" />
              {t('patterns.clearFilter')}
            </button>
          )}
        </div>

        {/* Sub-departments checkbox */}
        <div className="flex items-center gap-2 py-2.5 border-b text-small text-foreground">
          <Checkbox
            id="include-subdepts"
            checked={scope === 'sub'}
            onCheckedChange={(checked) => onScopeChange(checked ? 'sub' : 'one')}
          />
          <label htmlFor="include-subdepts" className="cursor-pointer select-none text-small">
            {t('peopleUI.filters.includeSubDepartments')}
          </label>
        </div>

        {/* Department search */}
        <div className="relative my-2">
          <Search className="pointer-events-none absolute left-2 top-2 size-3.5 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('fields.searchPlaceholder')}
            className="h-7 pl-7 text-xs"
          />
        </div>

        {/* Department tree list */}
        <div className="max-h-60 overflow-y-auto pt-1">
          {tree ? (
            filteredNodes.length > 0 ? (
              <TreeList
                nodes={filteredNodes}
                selected={base}
                onSelect={(n) => {
                  onBaseChange(n.dn)
                  setOpen(false)
                  setSearch('')
                }}
              />
            ) : (
              <div className="p-3 text-center text-xs text-muted-foreground">
                {t('fields.noResults')}
              </div>
            )
          ) : (
            <div className="p-3 text-center text-xs text-muted-foreground">
              {t('common.loading')}
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

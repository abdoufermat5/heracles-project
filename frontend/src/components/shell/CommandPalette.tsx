import { useNavigate, useRouterState } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Clock, Plus, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { qk, usePrefetch, useTypes } from '@/api/hooks'
import type { ObjectDetail, TypeDescriptor } from '@/api/types'
import { api } from '@/api/endpoints'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { useCapabilities } from '@/features/admin/hooks'
import { comboLabels } from '@/lib/hotkeys'
import { TypeIcon } from '@/lib/icons'
import { typeLabel, typeLabelPlural } from '@/lib/labels'
import { nameValue, rdnValue } from '@/lib/objects'
import { useTheme } from '@/lib/theme'
import { addRecentItem, clearRecentItems, getRecentItems } from './recent'
import {
  buildPaletteActions,
  currentObjectOf,
  fuzzyScore,
  navShortcuts,
  type PaletteAction,
} from './paletteActions'

function useDebounced<T>(value: T, ms = 220): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

const itemClass = 'flex items-center gap-2 px-2.5'
const badgeClass = 'shrink-0 whitespace-nowrap rounded-sm bg-muted px-1 text-caption text-muted-foreground'

/**
 * Types the object search skips: the audit trail, archives, registrations and scheduled
 * tasks are internal records, not something a person looks for by name; access roles are
 * edited from the access control page.
 */
function searchable(ty: { name: string }): boolean {
  return !/_task$/.test(ty.name) && !['audit_event', 'archived_object', 'registration', 'acl_role'].includes(ty.name)
}

function stringValue(values: Record<string, unknown>, key: string): string | undefined {
  const v = values[key]
  const first = Array.isArray(v) ? v[0] : v
  return typeof first === 'string' && first ? first : undefined
}

/** A palette row: an action or a destination, with an optional prefetch hint on intent. */
interface Entry extends PaletteAction {
  typeIcon?: string
  hint?: () => void
}

function Row({ entry, onSelect }: { entry: Entry; onSelect: () => void }) {
  const Icon = entry.icon
  return (
    <CommandItem
      value={entry.id}
      onSelect={onSelect}
      onMouseEnter={entry.hint}
      onFocus={entry.hint}
      className={itemClass + (entry.destructive ? ' text-destructive focus:text-destructive' : '')}
    >
      {entry.typeIcon ? (
        <TypeIcon name={entry.typeIcon} className="size-3.5 shrink-0" />
      ) : (
        <Icon className="size-3.5 shrink-0" aria-hidden />
      )}
      <span className="truncate">{entry.label}</span>
      {entry.detail && (
        <span className="font-dn text-muted-foreground ml-auto truncate text-caption max-w-[220px]">
          {entry.detail}
        </span>
      )}
      {entry.shortcut && <Kbd keys={comboLabels(entry.shortcut)} className="ml-auto" />}
    </CommandItem>
  )
}

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { toggle } = useTheme()
  const { data: types } = useTypes()
  const { data: caps } = useCapabilities()
  const prefetch = usePrefetch()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const [q, setQ] = useState('')
  const dq = useDebounced(q.trim())
  const recents = useMemo(() => (open ? getRecentItems() : []), [open])
  const search = useQuery({
    queryKey: ['palette-search', dq],
    enabled: open && dq.length >= 2 && !!types,
    queryFn: async () => {
      const results = await Promise.all(
        (types ?? []).filter(searchable).map(async (ty) => {
          const r = await api.listObjects(ty.name, { q: dq, limit: 5, scope: 'sub' }).catch(() => null)
          const items = r?.items ?? []
          if (items.length === 0) return { type: ty, items: [] }
          // the display name and the login live in two different attributes of the type
          const desc = await qc
            .ensureQueryData({ queryKey: qk.type(ty.name), queryFn: () => api.type(ty.name), staleTime: 5 * 60_000 })
            .catch(() => null)
          return {
            type: ty,
            items: items.map((it) => {
              const main = desc ? stringValue(it.values, desc.main_attr) : undefined
              const name = desc ? stringValue(it.values, desc.name_attr) : undefined
              const label = name ?? main ?? Object.values(it.values).find((v): v is string => typeof v === 'string') ?? rdnValue(it.dn)
              return { dn: it.dn, label, secondary: main && main !== label ? main : undefined }
            }),
          }
        }),
      )
      return results.filter((r) => r.items.length > 0)
    },
  })

  const run = (fn: () => void) => {
    onOpenChange(false)
    fn()
  }
  const go = (to: string, opts?: { params?: Record<string, string>; search?: Record<string, string> }) =>
    void navigate({ to: to as never, params: opts?.params as never, search: opts?.search as never })

  const logout = async () => {
    try {
      await api.logout()
    } finally {
      qc.clear()
      clearRecentItems()
      void navigate({ to: '/login' })
    }
  }

  const current = currentObjectOf(pathname)
  // The readable label comes from the object page's own cached detail, then the recents list.
  const loaded = current ? qc.getQueryData<ObjectDetail>(qk.object(current.type, current.dn)) : undefined
  const currentDesc = current ? qc.getQueryData<TypeDescriptor>(qk.type(current.type)) : undefined
  const currentTitle =
    loaded && currentDesc
      ? nameValue(currentDesc, loaded)
      : current
        ? (recents.find((r) => r.dn.toLowerCase() === current.dn.toLowerCase())?.title ?? rdnValue(current.dn))
        : undefined

  const entries = useMemo(() => {
    const canCreate = (name: string) => types?.find((ty) => ty.name === name)?.can_create === true
    const nav: Entry[] = navShortcuts(caps)
      .filter((n) => !n.cap || caps?.[n.cap])
      .map((n) => ({
        id: `nav:${n.combo}`,
        label: t(n.labelKey),
        icon: n.icon,
        shortcut: n.combo,
        run: () => go(n.to, { params: n.params }),
        hint: n.params?.type ? () => prefetch.type(n.params?.type ?? '') : undefined,
      }))
    const shortcutTypes = new Set(['user', 'group'])
    const typeNav: Entry[] = (types ?? [])
      .filter((ty) => !shortcutTypes.has(ty.name) && ty.name !== 'acl_role')
      .map((ty) => ({
        id: `type:${ty.name}`,
        label: typeLabelPlural(t, ty),
        icon: Clock,
        typeIcon: ty.icon,
        run: () => go('/types/$type', { params: { type: ty.name } }),
        hint: () => prefetch.type(ty.name),
      }))
    const actions: Entry[] = [
      ...buildPaletteActions({
        t,
        can: { createUser: canCreate('user'), createGroup: canCreate('group'), acl: caps?.acl === true },
        current,
        currentLabel: currentTitle,
        go,
        toggleTheme: toggle,
        switchLanguage: () => void i18n.changeLanguage(i18n.language.startsWith('fr') ? 'en' : 'fr'),
        signOut: () => void logout(),
        copyDn: (dn) => {
          navigator.clipboard.writeText(dn).then(
            () => toast.success(t('shellUI.palette.copied')),
            () => toast.error(t('shellUI.palette.copyFailed')),
          )
        },
      }),
      ...(types ?? [])
        .filter((ty) => ty.can_create && !shortcutTypes.has(ty.name) && ty.name !== 'acl_role')
        .map((ty) => ({
          id: `create:${ty.name}`,
          label: t('palette.create', { type: typeLabel(t, ty) }),
          icon: Plus,
          run: () => go('/types/$type/new', { params: { type: ty.name } }),
        })),
    ]
    return { nav, typeNav, actions }
    // go/logout/toggle are recreated every render; what matters is listed here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caps, types, t, current?.dn, currentTitle, i18n.language, open])

  const needle = q.trim()
  const rank = (items: Entry[]): Entry[] => {
    if (!needle) return items
    return items
      .map((it) => ({ it, s: fuzzyScore(needle, it.label) }))
      .filter((x): x is { it: Entry; s: number } => x.s !== null)
      .sort((a, b) => b.s - a.s)
      .map((x) => x.it)
  }
  const nav = rank(entries.nav)
  const typeNav = rank(entries.typeNav)
  const actions = rank(entries.actions)
  const recentHits = needle ? recents.filter((r) => fuzzyScore(needle, `${r.title} ${r.dn}`) !== null) : recents

  const onSelectObject = (type: string, dn: string, title: string) => {
    addRecentItem({ dn, type, title, subtitle: dn })
    run(() => go('/types/$type/$dn', { params: { type, dn } }))
  }
  const labelOfType = (name: string) => {
    const ty = types?.find((x) => x.name === name)
    return ty ? typeLabel(t, ty) : name
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setQ('')
        onOpenChange(o)
      }}
    >
      <DialogHeader className="sr-only">
        <DialogTitle>{t('palette.title')}</DialogTitle>
        <DialogDescription>{t('palette.description')}</DialogDescription>
      </DialogHeader>
      <DialogContent className="max-w-xl gap-0 overflow-hidden p-0" showCloseButton={false}>
        <Command shouldFilter={false} loop>
          <div className="relative">
            <CommandInput
              value={q}
              onValueChange={setQ}
              placeholder={t('palette.placeholder')}
              className="pr-8"
            />
            {q && (
              <button
                type="button"
                onClick={() => setQ('')}
                aria-label={t('listing.clearSearch')}
                className="absolute top-1/2 right-2 -translate-y-1/2 rounded-sm p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="size-3.5" aria-hidden />
              </button>
            )}
          </div>

          <CommandList className="max-h-96 p-1.5">
            <CommandEmpty className="py-8 text-center text-xs text-muted-foreground">
              {search.isFetching ? t('common.loading') : t('palette.empty')}
            </CommandEmpty>

            {recentHits.length > 0 && (
              <CommandGroup heading={t('palette.recent')}>
                {recentHits.map((item) => (
                  <CommandItem
                    key={`recent-${item.dn}`}
                    value={`recent-${item.dn}`}
                    onSelect={() => onSelectObject(item.type, item.dn, item.title)}
                    onMouseEnter={() => prefetch.object(item.type, item.dn)}
                    onFocus={() => prefetch.object(item.type, item.dn)}
                    className={itemClass}
                  >
                    <Clock className="size-3.5 text-muted-foreground shrink-0" aria-hidden />
                    <span className="font-medium text-foreground truncate">{item.title}</span>
                    <span className={badgeClass}>
                      {labelOfType(item.type)}
                    </span>
                    <span className="font-dn text-muted-foreground ml-auto truncate text-caption max-w-[220px]">
                      {item.dn}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            {actions.length > 0 && (
              <CommandGroup heading={t('palette.actions')}>
                {actions.map((a) => (
                  <Row key={a.id} entry={a} onSelect={() => run(a.run)} />
                ))}
              </CommandGroup>
            )}

            {nav.length + typeNav.length > 0 && (
              <CommandGroup heading={t('palette.navigate')}>
                {[...nav, ...typeNav].map((a) => (
                  <Row key={a.id} entry={a} onSelect={() => run(a.run)} />
                ))}
              </CommandGroup>
            )}

            {search.data && search.data.length > 0 && <CommandSeparator className="my-1" />}
            {search.data?.map((g) => (
              <CommandGroup key={g.type.name} heading={typeLabelPlural(t, g.type)}>
                {g.items.map((it) => {
                  const label = it.label
                  return (
                    <CommandItem
                      key={it.dn}
                      value={`obj-${it.dn}`}
                      onSelect={() => onSelectObject(g.type.name, it.dn, label)}
                      onMouseEnter={() => prefetch.object(g.type.name, it.dn)}
                      onFocus={() => prefetch.object(g.type.name, it.dn)}
                      className={itemClass}
                    >
                      <TypeIcon name={g.type.icon} className="size-3.5 text-muted-foreground shrink-0" />
                      <span className="font-medium text-foreground truncate">{label}</span>
                      <span className={badgeClass}>{typeLabel(t, g.type)}</span>
                      {it.secondary && (
                        <span className="truncate font-mono text-caption text-muted-foreground">{it.secondary}</span>
                      )}
                      <span className="font-dn text-muted-foreground ml-auto truncate text-caption max-w-[220px]">
                        {it.dn}
                      </span>
                    </CommandItem>
                  )
                })}
              </CommandGroup>
            ))}
          </CommandList>

          <div className="flex items-center justify-between border-t border-border bg-muted/30 px-3 py-2 text-caption text-muted-foreground">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1">
                <Kbd keys={['↑', '↓']} />
                <span>{t('palette.hints.navigate', 'Navigate')}</span>
              </span>
              <span className="flex items-center gap-1">
                <Kbd>↵</Kbd>
                <span>{t('palette.hints.select', 'Select')}</span>
              </span>
            </div>
            <span className="flex items-center gap-1">
              <Kbd>Esc</Kbd>
              <span>{t('palette.hints.close', 'Close')}</span>
            </span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  )
}

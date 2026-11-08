import { useNavigate } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Clock,
  LayoutDashboard,
  LogOut,
  Moon,
  Languages,
  Plus,
  X,
  User,
  ExternalLink,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useTypes } from '@/api/hooks'
import { api } from '@/api/endpoints'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { TypeIcon } from '@/lib/icons'
import { rdnValue } from '@/lib/objects'
import { useTheme } from '@/lib/theme'
import { addRecentItem, getRecentItems } from './recent'

function useDebounced<T>(value: T, ms = 220): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { toggle } = useTheme()
  const { data: types } = useTypes()
  const [q, setQ] = useState('')
  const dq = useDebounced(q.trim())
  const recents = useMemo(() => (open ? getRecentItems() : []), [open])
  const search = useQuery({
    queryKey: ['palette-search', dq],
    enabled: open && dq.length >= 2 && !!types,
    queryFn: async () => {
      const results = await Promise.all(
        (types ?? []).map(async (ty) => {
          const r = await api.listObjects(ty.name, { q: dq, limit: 5, scope: 'sub' }).catch(() => null)
          return { type: ty, items: r?.items ?? [] }
        }),
      )
      return results.filter((r) => r.items.length > 0)
    },
  })

  const run = (fn: () => void) => {
    onOpenChange(false)
    fn()
  }

  const needle = q.trim().toLowerCase()
  const match = (s: string) => !needle || s.toLowerCase().includes(needle)
  const creatable = types?.filter((ty) => ty.can_create && match(t('palette.create', { type: ty.label }))) ?? []
  const actionsVisible =
    creatable.length > 0 ||
    match(t('palette.toggleTheme')) ||
    match(t('palette.switchLanguage')) ||
    match(t('user.logout'))

  const logout = async () => {
    await api.logout()
    qc.clear()
    void navigate({ to: '/login' })
  }

  const onSelectObject = (type: string, dn: string, title: string) => {
    addRecentItem({ dn, type, title, subtitle: dn })
    run(() => void navigate({ to: '/types/$type/$dn', params: { type, dn } }))
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

            {/* Recent items when query is empty */}
            {!q.trim() && recents.length > 0 && (
              <CommandGroup heading={t('palette.recent', 'Recent objects')}>
                {recents.map((item) => (
                  <CommandItem
                    key={`recent-${item.dn}`}
                    value={`recent-${item.dn}`}
                    onSelect={() => onSelectObject(item.type, item.dn, item.title)}
                    className="flex items-center gap-2 px-2.5"
                  >
                    <Clock className="size-3.5 text-muted-foreground shrink-0" />
                    <span className="font-medium text-foreground truncate">{item.title}</span>
                    <span className="font-dn text-muted-foreground ml-auto truncate text-caption max-w-[200px]">
                      {item.dn}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            {/* Navigation Group */}
            {match(t('nav.dashboard')) && (
              <CommandGroup heading={t('palette.navigate')}>
                <CommandItem
                  value="nav-dashboard"
                  onSelect={() => run(() => void navigate({ to: '/' }))}
                  className="flex items-center gap-2 px-2.5"
                >
                  <LayoutDashboard className="size-3.5 shrink-0" />
                  <span>{t('nav.dashboard')}</span>
                </CommandItem>
                <CommandItem
                  value="nav-me"
                  onSelect={() => run(() => void navigate({ to: '/me' }))}
                  className="flex items-center gap-2 px-2.5"
                >
                  <User className="size-3.5 shrink-0" />
                  <span>{t('user.me')}</span>
                </CommandItem>
                {types
                  ?.filter((ty) => match(ty.label_plural))
                  .map((ty) => (
                    <CommandItem
                      key={ty.name}
                      value={`nav-${ty.name}`}
                      onSelect={() => run(() => void navigate({ to: '/types/$type', params: { type: ty.name } }))}
                      className="flex items-center gap-2 px-2.5"
                    >
                      <TypeIcon name={ty.icon} className="size-3.5 shrink-0" />
                      <span>{ty.label_plural}</span>
                    </CommandItem>
                  ))}
              </CommandGroup>
            )}

            {/* Actions Group */}
            {actionsVisible && (
            <CommandGroup heading={t('palette.actions')}>
              {creatable.map((ty) => (
                  <CommandItem
                    key={ty.name}
                    value={`create-${ty.name}`}
                    onSelect={() => run(() => void navigate({ to: '/types/$type/new', params: { type: ty.name } }))}
                    className="flex items-center gap-2 px-2.5"
                  >
                    <Plus className="size-3.5 shrink-0 text-primary" />
                    <span>{t('palette.create', { type: ty.label })}</span>
                  </CommandItem>
                ))}
              {match(t('palette.toggleTheme')) && (
                <CommandItem
                  value="toggle-theme"
                  onSelect={() => run(toggle)}
                  className="flex items-center gap-2 px-2.5"
                >
                  <Moon className="size-3.5 shrink-0" />
                  <span>{t('palette.toggleTheme')}</span>
                </CommandItem>
              )}
              {match(t('palette.switchLanguage')) && (
                <CommandItem
                  value="switch-language"
                  onSelect={() => run(() => void i18n.changeLanguage(i18n.language.startsWith('fr') ? 'en' : 'fr'))}
                  className="flex items-center gap-2 px-2.5"
                >
                  <Languages className="size-3.5 shrink-0" />
                  <span>{t('palette.switchLanguage')}</span>
                </CommandItem>
              )}
              {match(t('user.logout')) && (
                <CommandItem
                  value="logout"
                  onSelect={() => run(() => void logout())}
                  className="flex items-center gap-2 px-2.5 text-destructive focus:text-destructive"
                >
                  <LogOut className="size-3.5 shrink-0" />
                  <span>{t('user.logout')}</span>
                </CommandItem>
              )}
            </CommandGroup>
            )}

            {/* Search Results */}
            {search.data && search.data.length > 0 && <CommandSeparator className="my-1" />}
            {search.data?.map((g) => (
              <CommandGroup key={g.type.name} heading={g.type.label_plural}>
                {g.items.map((it) => {
                  const first = Object.values(it.values).find((v) => typeof v === 'string')
                  const label = typeof first === 'string' ? first : rdnValue(it.dn)
                  return (
                    <CommandItem
                      key={it.dn}
                      value={`obj-${it.dn}`}
                      onSelect={() => onSelectObject(g.type.name, it.dn, label)}
                      className="flex items-center gap-2 px-2.5"
                    >
                      <TypeIcon name={g.type.icon} className="size-3.5 text-muted-foreground shrink-0" />
                      <span className="font-medium text-foreground truncate">{label}</span>
                      <span className="font-dn text-muted-foreground ml-auto truncate text-caption max-w-[220px]">
                        {it.dn}
                      </span>
                      <ExternalLink className="size-3 text-muted-foreground/60 shrink-0 ml-1" />
                    </CommandItem>
                  )
                })}
              </CommandGroup>
            ))}
          </CommandList>

          {/* Keyboard hints footer */}
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

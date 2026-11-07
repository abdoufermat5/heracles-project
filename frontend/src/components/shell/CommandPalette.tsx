import { useNavigate } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { LayoutDashboard, LogOut, Moon, Languages, Plus, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useTypes } from '@/api/hooks'
import { api } from '@/api/endpoints'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { TypeIcon } from '@/lib/icons'
import { rdnValue } from '@/lib/objects'
import { useTheme } from '@/lib/theme'

function useDebounced<T>(value: T, ms = 250): T {
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

  const logout = async () => {
    await api.logout()
    qc.clear()
    void navigate({ to: '/login' })
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
      <DialogContent className="overflow-hidden p-0" showCloseButton={false}>
        <Command shouldFilter={false} loop>
          <CommandInput value={q} onValueChange={setQ} placeholder={t('palette.placeholder')} />
          <CommandList className="max-h-96">
            <CommandEmpty>{search.isFetching ? t('common.loading') : t('palette.empty')}</CommandEmpty>

            {match(t('nav.dashboard')) && (
              <CommandGroup heading={t('palette.navigate')}>
                <CommandItem value="nav-dashboard" onSelect={() => run(() => void navigate({ to: '/' }))}>
                  <LayoutDashboard className="size-4" />
                  {t('nav.dashboard')}
                </CommandItem>
                {types
                  ?.filter((ty) => match(ty.label_plural))
                  .map((ty) => (
                    <CommandItem
                      key={ty.name}
                      value={`nav-${ty.name}`}
                      onSelect={() => run(() => void navigate({ to: '/types/$type', params: { type: ty.name } }))}
                    >
                      <TypeIcon name={ty.icon} className="size-4" />
                      {ty.label_plural}
                    </CommandItem>
                  ))}
              </CommandGroup>
            )}

            <CommandGroup heading={t('palette.actions')}>
              {types
                ?.filter((ty) => ty.can_create && match(t('palette.create', { type: ty.label })))
                .map((ty) => (
                  <CommandItem
                    key={ty.name}
                    value={`create-${ty.name}`}
                    onSelect={() => run(() => void navigate({ to: '/types/$type/new', params: { type: ty.name } }))}
                  >
                    <Plus className="size-4" />
                    {t('palette.create', { type: ty.label })}
                  </CommandItem>
                ))}
              {match(t('palette.toggleTheme')) && (
                <CommandItem value="toggle-theme" onSelect={() => run(toggle)}>
                  <Moon className="size-4" />
                  {t('palette.toggleTheme')}
                </CommandItem>
              )}
              {match(t('palette.switchLanguage')) && (
                <CommandItem
                  value="switch-language"
                  onSelect={() => run(() => void i18n.changeLanguage(i18n.language.startsWith('fr') ? 'en' : 'fr'))}
                >
                  <Languages className="size-4" />
                  {t('palette.switchLanguage')}
                </CommandItem>
              )}
              {match(t('user.logout')) && (
                <CommandItem value="logout" onSelect={() => run(() => void logout())}>
                  <LogOut className="size-4" />
                  {t('user.logout')}
                </CommandItem>
              )}
            </CommandGroup>

            {search.data?.map((g) => (
              <CommandGroup key={g.type.name} heading={g.type.label_plural}>
                {g.items.map((it) => {
                  const first = Object.values(it.values).find((v) => typeof v === 'string')
                  return (
                    <CommandItem
                      key={it.dn}
                      value={`obj-${it.dn}`}
                      onSelect={() =>
                        run(() => void navigate({ to: '/types/$type/$dn', params: { type: g.type.name, dn: it.dn } }))
                      }
                    >
                      <Search className="size-4" />
                      <span className="truncate">{typeof first === 'string' ? first : rdnValue(it.dn)}</span>
                      <span className="font-dn text-muted-foreground ml-auto truncate text-xs">{it.dn}</span>
                    </CommandItem>
                  )
                })}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  )
}

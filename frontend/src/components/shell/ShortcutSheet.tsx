import { useNavigate } from '@tanstack/react-router'
import { useEffect, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { useCapabilities } from '@/features/admin/hooks'
import { comboLabels, focusPageSearch, registerHotkey, useGlobalHotkeys, useHotkey, useHotkeyList } from '@/lib/hotkeys'
import { navShortcuts } from './paletteActions'

/**
 * Registers the console-wide shortcuts: `mod+k`, `?`, `/` and the `g x` navigation
 * sequences. Mount once, in the shell.
 */
export function useShellHotkeys({
  togglePalette,
  toggleSheet,
}: {
  togglePalette: () => void
  toggleSheet: () => void
}): void {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const navigateRef = useRef(navigate)
  useEffect(() => {
    navigateRef.current = navigate
  })
  const { data: caps } = useCapabilities()
  useGlobalHotkeys()
  useHotkey('mod+k', togglePalette, { description: t('shellUI.shortcuts.palette'), scope: 'global' })
  useHotkey('?', toggleSheet, { description: t('shellUI.shortcuts.sheet'), scope: 'global' })
  useHotkey('/', () => void focusPageSearch(), { description: t('shellUI.shortcuts.search'), scope: 'global' })

  const nav = useMemo(() => navShortcuts(caps).filter((n) => !n.cap || caps?.[n.cap]), [caps])
  useEffect(() => {
    const offs = nav.map((n) =>
      registerHotkey(
        n.combo,
        () => void navigateRef.current({ to: n.to as never, params: n.params as never }),
        { description: t(n.labelKey), scope: 'navigation' },
      ),
    )
    return () => offs.forEach((off) => off())
  }, [nav, t])
}

const SCOPE_ORDER = ['global', 'navigation']

export function ShortcutSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation()
  const all = useHotkeyList()
  const groups = useMemo(() => {
    const by = new Map<string, typeof all>()
    for (const e of all) {
      if (!e.description) continue
      by.set(e.scope, [...(by.get(e.scope) ?? []), e])
    }
    return [...by.entries()].sort(
      ([a], [b]) => (SCOPE_ORDER.indexOf(a) + 1 || 99) - (SCOPE_ORDER.indexOf(b) + 1 || 99),
    )
  }, [all])
  const scopeLabel = (s: string) => t(`shellUI.shortcuts.scopes.${s}`, { defaultValue: s })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('shellUI.shortcuts.title')}</DialogTitle>
          <DialogDescription>{t('shellUI.shortcuts.description')}</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-4 overflow-y-auto">
          {groups.length === 0 && (
            <p className="text-body text-muted-foreground">{t('shellUI.shortcuts.empty')}</p>
          )}
          {groups.map(([scope, list]) => (
            <section key={scope} aria-label={scopeLabel(scope)}>
              <h3 className="label-caps pb-1 text-muted-foreground">{scopeLabel(scope)}</h3>
              <ul className="divide-y divide-border/60">
                {list.map((e) => (
                  <li key={e.id} className="flex items-center justify-between gap-3 py-1.5 text-body">
                    <span>{e.description}</span>
                    <Kbd keys={comboLabels(e.combo)} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}

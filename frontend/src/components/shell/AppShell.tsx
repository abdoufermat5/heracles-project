import { Link, Outlet, useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import {
  Building2,
  Globe,
  Languages,
  LogOut,
  Menu,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  RotateCcw,
  Search,
  Sun,
  User as UserIcon,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMe, useTree } from '@/api/hooks'
import { api } from '@/api/endpoints'
import type { TreeNode } from '@/api/types'
import { Logo } from '@/components/Logo'
import { TreeList } from '@/components/fields/RefFields'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Kbd } from '@/components/ui/kbd'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { TooltipProvider } from '@/components/ui/tooltip'
import { setTechnicalDetails, useTechnicalDetails } from '@/lib/preferences'
import { useScope } from '@/lib/scope'
import { useTheme, type ThemeChoice } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { CommandPalette } from './CommandPalette'
import { SidebarNav } from './Sidebar'

const COLLAPSE_KEY = 'heracles.sidebar.collapsed'

function pathTo(nodes: TreeNode[], dn: string, acc: TreeNode[] = []): TreeNode[] | null {
  for (const n of nodes) {
    const next = [...acc, n]
    if (n.dn.toLowerCase() === dn.toLowerCase()) return next
    const r = pathTo(n.children, dn, next)
    if (r) return r
  }
  return null
}

function DepartmentSwitcher() {
  const { t } = useTranslation()
  const { data: tree } = useTree()
  const { data: me } = useMe()
  const { base, setBase } = useScope()
  const [open, setOpen] = useState(false)
  const current = base ?? me?.base ?? null
  const path = useMemo(() => (tree && current ? pathTo(tree, current) : null), [tree, current])
  const isCustomScope = base !== null && base !== me?.base

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 max-w-xs gap-1.5 px-2 font-normal"
          aria-label={t('shell.department')}
        >
          <Building2 className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <nav aria-label={t('shell.breadcrumb')} className="min-w-0">
            <ol className="flex items-center gap-1 truncate text-body">
              {isCustomScope && (
                <li className="flex items-center" aria-hidden>
                  <span className="size-1.5 rounded-full bg-signal" />
                </li>
              )}
              {(path ?? []).map((n, i) => (
                <li key={n.dn} className="flex items-center gap-1">
                  {i > 0 && <span className="text-muted-foreground/60">/</span>}
                  <span className={cn(i === (path?.length ?? 0) - 1 ? 'font-medium text-foreground' : 'text-muted-foreground')}>
                    {n.label}
                  </span>
                </li>
              ))}
              {!path && <li className="text-muted-foreground">{t('shell.department')}</li>}
            </ol>
          </nav>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-2">
        <div className="flex items-center justify-between border-b border-border/70 px-2 py-1.5 pb-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold tracking-tight text-foreground">
            <Globe className="size-3.5 text-muted-foreground" />
            <span>{t('fields.selectDepartment')}</span>
          </div>
          {isCustomScope && (
            <Button
              variant="ghost"
              size="xs"
              onClick={() => {
                setBase(null)
                setOpen(false)
              }}
              className="h-6 gap-1 text-caption text-muted-foreground hover:text-foreground"
            >
              <RotateCcw className="size-3" />
              <span>Reset</span>
            </Button>
          )}
        </div>
        <div className="max-h-80 overflow-y-auto pt-1.5">
          {tree && (
            <TreeList
              nodes={tree}
              selected={current}
              onSelect={(n) => {
                setBase(n.dn === me?.base ? null : n.dn)
                setOpen(false)
              }}
            />
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

/** Account menu; the portal variant leaves out console-only settings. */
export function UserMenu({ portal = false }: { portal?: boolean }) {
  const { t, i18n } = useTranslation()
  const technical = useTechnicalDetails()
  const { data: me } = useMe()
  const { theme, setTheme } = useTheme()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const logout = async () => {
    try {
      await api.logout()
    } finally {
      qc.clear()
      void navigate({ to: '/login' })
    }
  }

  const initials = (me?.display_name ?? me?.uid ?? '?')
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()
  const lang = i18n.language.startsWith('fr') ? 'fr' : 'en'

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className="h-8 gap-2 px-1.5"
          aria-label={t('user.menu')}
        >
          <Avatar className="size-7 border border-border">
            {me?.avatar_url && <AvatarImage src={me.avatar_url} alt="" />}
            <AvatarFallback className="bg-muted text-caption font-semibold text-foreground">{initials}</AvatarFallback>
          </Avatar>
          <span className="hidden min-w-0 flex-col items-start leading-tight lg:flex">
            <span className="max-w-36 truncate text-body font-medium text-foreground">
              {me?.display_name}
            </span>
            <span className="max-w-36 truncate font-mono text-caption text-muted-foreground">
              {me?.uid}
            </span>
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="px-2 py-2 font-normal">
          <p className="truncate text-body font-semibold text-foreground">{me?.display_name}</p>
          <p className="truncate font-mono text-caption text-muted-foreground">{me?.uid}</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void navigate({ to: '/me' })} className="gap-2">
          <UserIcon className="size-3.5" />
          <span>{t('user.me')}</span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="flex items-center gap-1.5 px-2 py-1.5 text-caption font-semibold uppercase tracking-[0.06em] text-muted-foreground">
          <Sun className="size-3" />
          <span>{t('user.theme')}</span>
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as ThemeChoice)}>
          <DropdownMenuRadioItem value="system">
            <Monitor className="size-3.5 mr-1" />
            {t('user.themeSystem')}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">
            <Sun className="size-3.5 mr-1" />
            {t('user.themeLight')}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <Moon className="size-3.5 mr-1" />
            {t('user.themeDark')}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        {!portal && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuCheckboxItem
              checked={technical}
              onSelect={(e) => e.preventDefault()}
              onCheckedChange={(on) => setTechnicalDetails(on === true)}
            >
              {t('patterns.technicalDetails')}
            </DropdownMenuCheckboxItem>
          </>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="flex items-center gap-1.5 px-2 py-1.5 text-caption font-semibold uppercase tracking-[0.06em] text-muted-foreground">
          <Languages className="size-3" />
          <span>{t('user.language')}</span>
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup value={lang} onValueChange={(v) => void i18n.changeLanguage(v)}>
          <DropdownMenuRadioItem value="en">English</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="fr">Français</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()} className="gap-2 text-destructive focus:text-destructive">
          <LogOut className="size-3.5" />
          <span>{t('user.logout')}</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function AppShell() {
  const { t, i18n } = useTranslation()
  const { resolved, toggle } = useTheme()
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === '1'
    } catch {
      return false
    }
  })
  const [mobileNav, setMobileNav] = useState(false)
  const [palette, setPalette] = useState(false)

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [collapsed])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPalette((p) => !p)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-dvh overflow-hidden bg-background">
        <a
          href="#main"
          className="sr-only z-50 rounded-md border border-border bg-card px-3 py-2 text-body font-medium text-foreground focus:not-sr-only focus:absolute focus:top-2 focus:left-2 outline-none focus:ring-2 focus:ring-ring"
        >
          {t('shell.skip')}
        </a>

        {/* Desktop Collapsible Left Sidebar */}
        <aside
          className={cn(
            'bg-sidebar hidden shrink-0 flex-col border-r border-sidebar-border transition-[width] duration-200 ease-in-out md:flex',
            collapsed ? 'w-14' : 'w-56',
          )}
        >
          <div className={cn('flex h-12 shrink-0 items-center border-b border-sidebar-border px-3.5', collapsed && 'justify-center px-0')}>
            <Link to="/" aria-label="Heracles" className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-sidebar">
              <Logo collapsed={collapsed} tone="inverse" />
            </Link>
          </div>
          <div className="flex-1 overflow-y-auto">
            <SidebarNav collapsed={collapsed} />
          </div>
          <div className={cn('border-t border-sidebar-border p-2', collapsed && 'flex justify-center')}>
            <Button
              variant="ghost"
              size={collapsed ? 'icon' : 'sm'}
              onClick={() => setCollapsed((c) => !c)}
              aria-label={collapsed ? t('shell.expand') : t('shell.collapse')}
              aria-pressed={collapsed}
              className={cn('text-sidebar-muted hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-offset-sidebar', !collapsed && 'w-full justify-start gap-2')}
            >
              {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
              {!collapsed && <span className="text-body font-medium">{t('shell.collapse')}</span>}
            </Button>
          </div>
        </aside>

        {/* Mobile Navigation Sheet */}
        <Sheet open={mobileNav} onOpenChange={setMobileNav}>
          <SheetContent side="left" className="w-68 border-sidebar-border bg-sidebar p-0 text-sidebar-foreground">
            <SheetHeader className="border-b border-sidebar-border p-4">
              <SheetTitle>
                <Logo tone="inverse" />
              </SheetTitle>
              <SheetDescription className="sr-only">{t('nav.main')}</SheetDescription>
            </SheetHeader>
            <div className="overflow-y-auto" onClick={() => setMobileNav(false)}>
              <SidebarNav />
            </div>
          </SheetContent>
        </Sheet>

        {/* Main Application Container */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* Top Header Bar */}
          <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-card px-3 md:px-5">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden size-8"
              onClick={() => setMobileNav(true)}
              aria-label={t('shell.openMenu')}
            >
              <Menu className="size-4" />
            </Button>

            <DepartmentSwitcher />

            <div className="ml-auto flex items-center gap-1.5">
              {/* Global Search Trigger */}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPalette(true)}
                className="hidden h-8 w-64 justify-between border-input bg-background px-2.5 font-normal text-muted-foreground hover:bg-background sm:flex"
                aria-label={t('shell.search')}
              >
                <span className="flex items-center gap-2 text-body">
                  <Search className="size-3.5 text-muted-foreground" aria-hidden />
                  <span>{t('shell.searchPlaceholder')}</span>
                </span>
                <Kbd keys={['⌘', 'K']} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="sm:hidden size-8"
                onClick={() => setPalette(true)}
                aria-label={t('shell.search')}
              >
                <Search className="size-4" />
              </Button>

              {/* Language Quick Toggle */}
              <Button
                variant="ghost"
                size="icon"
                className="size-8 text-muted-foreground hover:text-foreground"
                onClick={() => void i18n.changeLanguage(i18n.language.startsWith('fr') ? 'en' : 'fr')}
                aria-label={t('user.language')}
              >
                <Languages className="size-4" />
              </Button>

              {/* Theme Quick Toggle */}
              <Button
                variant="ghost"
                size="icon"
                className="size-8 text-muted-foreground hover:text-foreground"
                onClick={toggle}
                aria-label={t('user.toggleTheme')}
              >
                {resolved === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
              </Button>

              <span className="mx-1 h-5 w-px bg-border" aria-hidden />

              {/* User Profile Menu */}
              <UserMenu />
            </div>
          </header>

          {/* Main Content Area */}
          <main id="main" tabIndex={-1} className="flex-1 overflow-y-auto outline-none">
            <div className="mx-auto flex min-h-full w-full max-w-[1400px] flex-col px-4 py-4 md:px-6 md:py-5">
              <Outlet />
            </div>
          </main>
        </div>

        {/* Global Command Palette */}
        <CommandPalette open={palette} onOpenChange={setPalette} />
      </div>
    </TooltipProvider>
  )
}

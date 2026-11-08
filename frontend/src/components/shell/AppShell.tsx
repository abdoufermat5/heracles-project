import { Link, Outlet, useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import {
  Building2,
  ChevronRight,
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
          variant="outline"
          size="sm"
          className={cn(
            'h-8 max-w-xs gap-1.5 border-border/80 bg-background/50 px-2.5 font-normal shadow-xs',
            isCustomScope && 'border-primary/50 bg-primary/5 text-primary',
          )}
          aria-label={t('shell.department')}
        >
          <Building2 className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <nav aria-label={t('shell.breadcrumb')} className="min-w-0">
            <ol className="flex items-center gap-1 truncate text-xs">
              {(path ?? []).map((n, i) => (
                <li key={n.dn} className="flex items-center gap-1">
                  {i > 0 && <ChevronRight className="text-muted-foreground/60 size-2.5" aria-hidden />}
                  <span className={cn(i === (path?.length ?? 0) - 1 ? 'font-medium text-foreground' : 'text-muted-foreground')}>
                    {n.label}
                  </span>
                </li>
              ))}
              {!path && <li>{t('shell.department')}</li>}
            </ol>
          </nav>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-2 shadow-lg">
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
              className="h-6 gap-1 text-[11px] text-muted-foreground hover:text-foreground"
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

function UserMenu() {
  const { t, i18n } = useTranslation()
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
          size="icon"
          className="size-8 rounded-full ring-offset-background transition-shadow focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={t('user.menu')}
        >
          <Avatar className="size-7.5 border border-border/80">
            {me?.avatar_url && <AvatarImage src={me.avatar_url} alt="" />}
            <AvatarFallback className="bg-primary-soft text-[11px] font-semibold text-foreground">{initials}</AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60 shadow-lg">
        <DropdownMenuLabel className="font-normal px-2.5 py-2">
          <p className="text-xs font-semibold text-foreground truncate">{me?.display_name}</p>
          <p className="text-muted-foreground font-mono text-[11px] truncate">{me?.uid}</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void navigate({ to: '/me' })} className="gap-2 text-xs">
          <UserIcon className="size-3.5" />
          <span>{t('user.me')}</span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-muted-foreground flex items-center gap-1.5 text-[11px] uppercase tracking-wider font-semibold">
          <Sun className="size-3" />
          <span>{t('user.theme')}</span>
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as ThemeChoice)}>
          <DropdownMenuRadioItem value="system" className="text-xs">
            <Monitor className="size-3.5 mr-1" />
            {t('user.themeSystem')}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light" className="text-xs">
            <Sun className="size-3.5 mr-1" />
            {t('user.themeLight')}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark" className="text-xs">
            <Moon className="size-3.5 mr-1" />
            {t('user.themeDark')}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-muted-foreground flex items-center gap-1.5 text-[11px] uppercase tracking-wider font-semibold">
          <Languages className="size-3" />
          <span>{t('user.language')}</span>
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup value={lang} onValueChange={(v) => void i18n.changeLanguage(v)}>
          <DropdownMenuRadioItem value="en" className="text-xs">English</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="fr" className="text-xs">Français</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()} className="gap-2 text-xs text-destructive focus:text-destructive">
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
          className="bg-primary text-primary-foreground sr-only z-50 rounded-md px-3 py-2 text-xs font-medium focus:not-sr-only focus:absolute focus:top-2 focus:left-2 shadow-md outline-none focus:ring-2 focus:ring-ring"
        >
          {t('shell.skip')}
        </a>

        {/* Desktop Collapsible Left Sidebar */}
        <aside
          className={cn(
            'bg-sidebar hidden shrink-0 flex-col border-r border-sidebar-border transition-[width] duration-200 ease-in-out md:flex',
            collapsed ? 'w-14' : 'w-60',
          )}
        >
          <div className={cn('flex h-13 items-center border-b border-sidebar-border px-3.5', collapsed && 'justify-center px-0')}>
            <Link to="/" aria-label="Heracles" className="outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-md">
              <Logo collapsed={collapsed} />
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
              className={cn('text-muted-foreground hover:text-sidebar-accent-foreground', !collapsed && 'w-full justify-start gap-2')}
            >
              {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
              {!collapsed && <span className="text-xs font-medium">{t('shell.collapse')}</span>}
            </Button>
          </div>
        </aside>

        {/* Mobile Navigation Sheet */}
        <Sheet open={mobileNav} onOpenChange={setMobileNav}>
          <SheetContent side="left" className="bg-sidebar w-68 p-0 border-sidebar-border">
            <SheetHeader className="border-b border-sidebar-border p-4">
              <SheetTitle>
                <Logo />
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
          <header className="bg-background/80 flex h-13 shrink-0 items-center gap-2 border-b border-border/80 px-3 backdrop-blur-sm md:px-5">
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
                className="text-muted-foreground hidden h-8 w-60 justify-between border-border/80 bg-background/50 font-normal shadow-xs hover:border-input sm:flex"
                aria-label={t('shell.search')}
              >
                <span className="flex items-center gap-2 text-xs">
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

              {/* User Profile Menu */}
              <UserMenu />
            </div>
          </header>

          {/* Main Content Area */}
          <main id="main" tabIndex={-1} className="flex-1 overflow-y-auto outline-none">
            <div className="mx-auto w-full max-w-7xl p-4 md:p-6 lg:p-8">
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

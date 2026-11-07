import { Link, Outlet, useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import {
  Building2,
  ChevronRight,
  Languages,
  LogOut,
  Menu,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
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

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="max-w-xs gap-1.5" aria-label={t('shell.department')}>
          <Building2 className="size-4 shrink-0" aria-hidden />
          <nav aria-label={t('shell.breadcrumb')} className="min-w-0">
            <ol className="flex items-center gap-1 truncate">
              {(path ?? []).map((n, i) => (
                <li key={n.dn} className="flex items-center gap-1">
                  {i > 0 && <ChevronRight className="text-muted-foreground size-3" aria-hidden />}
                  <span className={cn(i === (path?.length ?? 0) - 1 ? 'font-medium' : 'text-muted-foreground')}>
                    {n.label}
                  </span>
                </li>
              ))}
              {!path && <li>{t('shell.department')}</li>}
            </ol>
          </nav>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="max-h-96 w-72 overflow-auto p-2">
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
        <Button variant="ghost" size="icon" className="rounded-full" aria-label={t('user.menu')}>
          <Avatar className="size-8">
            {me?.avatar_url && <AvatarImage src={me.avatar_url} alt="" />}
            <AvatarFallback className="bg-primary-soft text-xs">{initials}</AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="font-normal">
          <p className="text-sm font-medium">{me?.display_name}</p>
          <p className="text-muted-foreground text-xs">{me?.uid}</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void navigate({ to: '/me' })}>
          <UserIcon className="size-4" />
          {t('user.me')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-muted-foreground flex items-center gap-2 text-xs">
          <Sun className="size-3.5" />
          {t('user.theme')}
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as ThemeChoice)}>
          <DropdownMenuRadioItem value="system">
            <Monitor className="size-4" />
            {t('user.themeSystem')}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">
            <Sun className="size-4" />
            {t('user.themeLight')}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <Moon className="size-4" />
            {t('user.themeDark')}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-muted-foreground flex items-center gap-2 text-xs">
          <Languages className="size-3.5" />
          {t('user.language')}
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup value={lang} onValueChange={(v) => void i18n.changeLanguage(v)}>
          <DropdownMenuRadioItem value="en">English</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="fr">Français</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()}>
          <LogOut className="size-4" />
          {t('user.logout')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function AppShell() {
  const { t } = useTranslation()
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
      <div className="flex h-dvh overflow-hidden">
        <a
          href="#main"
          className="bg-primary text-primary-foreground sr-only z-50 rounded-md px-3 py-2 focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
        >
          {t('shell.skip')}
        </a>
        <aside
          className={cn(
            'bg-sidebar hidden shrink-0 flex-col border-r transition-[width] duration-200 md:flex',
            collapsed ? 'w-14' : 'w-60',
          )}
        >
          <div className={cn('flex h-14 items-center border-b px-3', collapsed && 'justify-center px-0')}>
            <Link to="/" aria-label="Heracles">
              <Logo collapsed={collapsed} />
            </Link>
          </div>
          <div className="flex-1 overflow-y-auto">
            <SidebarNav collapsed={collapsed} />
          </div>
          <div className={cn('border-t p-2', collapsed && 'flex justify-center')}>
            <Button
              variant="ghost"
              size={collapsed ? 'icon' : 'sm'}
              onClick={() => setCollapsed((c) => !c)}
              aria-label={collapsed ? t('shell.expand') : t('shell.collapse')}
              aria-pressed={collapsed}
              className={cn(!collapsed && 'w-full justify-start')}
            >
              {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
              {!collapsed && t('shell.collapse')}
            </Button>
          </div>
        </aside>

        <Sheet open={mobileNav} onOpenChange={setMobileNav}>
          <SheetContent side="left" className="bg-sidebar w-64 p-0">
            <SheetHeader className="border-b p-4">
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

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="bg-background/80 flex h-14 shrink-0 items-center gap-2 border-b px-3 backdrop-blur md:px-5">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              onClick={() => setMobileNav(true)}
              aria-label={t('shell.openMenu')}
            >
              <Menu className="size-4" />
            </Button>
            <DepartmentSwitcher />
            <div className="ml-auto flex items-center gap-1.5">
              <Button
                variant="outline"
                onClick={() => setPalette(true)}
                className="text-muted-foreground hidden w-64 justify-between font-normal sm:flex"
                aria-label={t('shell.search')}
              >
                <span className="flex items-center gap-2">
                  <Search className="size-4" aria-hidden />
                  {t('shell.searchPlaceholder')}
                </span>
                <kbd className="bg-muted rounded px-1.5 py-0.5 font-mono text-[11px]">⌘K</kbd>
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="sm:hidden"
                onClick={() => setPalette(true)}
                aria-label={t('shell.search')}
              >
                <Search className="size-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={toggle}
                aria-label={t('user.toggleTheme')}
              >
                {resolved === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
              </Button>
              <UserMenu />
            </div>
          </header>
          <main id="main" tabIndex={-1} className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-6xl p-4 md:p-8">
              <Outlet />
            </div>
          </main>
        </div>
        <CommandPalette open={palette} onOpenChange={setPalette} />
      </div>
    </TooltipProvider>
  )
}

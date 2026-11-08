import { Link, Navigate, Outlet, useRouterState } from '@tanstack/react-router'
import { Languages, Moon, Sun } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Logo } from '@/components/Logo'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useTheme } from '@/lib/theme'
import { UserMenu } from './AppShell'

/** Pages of the self-service portal; anything else leads back to its home. */
const PORTAL_PATHS = ['/me']

/**
 * Shell of the self-service portal: a calm single column for employees who
 * manage only their own account. No administration vocabulary, no directory
 * internals.
 */
export function PortalShell() {
  const { t, i18n } = useTranslation()
  const { resolved, toggle } = useTheme()
  const path = useRouterState({ select: (s) => s.location.pathname })

  if (!PORTAL_PATHS.includes(path)) return <Navigate to="/me" replace />

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex min-h-dvh flex-col bg-background">
        <a
          href="#main"
          className="sr-only z-50 rounded-md border bg-card px-3 py-2 text-body font-medium focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
        >
          {t('shell.skip')}
        </a>
        <header className="sticky top-0 z-30 border-b bg-card/95 backdrop-blur">
          <div className="mx-auto flex h-14 w-full max-w-4xl items-center gap-3 px-4">
            <Link to="/me" aria-label="Heracles" className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Logo />
            </Link>
            <span className="hidden text-body text-muted-foreground sm:inline">{t('portal.title')}</span>
            <div className="ml-auto flex items-center gap-1.5">
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground hover:text-foreground"
                onClick={() => void i18n.changeLanguage(i18n.language.startsWith('fr') ? 'en' : 'fr')}
                aria-label={t('user.language')}
              >
                <Languages className="size-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground hover:text-foreground"
                onClick={toggle}
                aria-label={t('user.toggleTheme')}
              >
                {resolved === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
              </Button>
              <UserMenu portal />
            </div>
          </div>
        </header>
        <main id="main" tabIndex={-1} className="flex-1 outline-none">
          <div className="mx-auto w-full max-w-4xl px-4 py-6 md:py-8">
            <Outlet />
          </div>
        </main>
      </div>
    </TooltipProvider>
  )
}

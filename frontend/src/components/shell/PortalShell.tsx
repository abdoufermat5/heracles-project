import { Link, Navigate, Outlet, useRouterState } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Logo } from '@/components/Logo'
import { TooltipProvider } from '@/components/ui/tooltip'
import { UserMenu } from './AppShell'
import { LanguageMenu, ThemeMenu } from './PreferenceMenus'

/**
 * Console pages lead back to the portal home. Only those: while signing out the
 * shell is still mounted on its way to /login, which must not be redirected.
 */
const CONSOLE_PATH = /^\/($|types(\/|$)|admin(\/|$)|io$|styleguide$)/

/**
 * Shell of the self-service portal: a calm single column for employees who
 * manage only their own account. No administration vocabulary, no directory
 * internals.
 */
export function PortalShell() {
  const { t } = useTranslation()
  const path = useRouterState({ select: (s) => s.location.pathname })

  if (CONSOLE_PATH.test(path)) return <Navigate to="/me" replace />

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
              <LanguageMenu />
              <ThemeMenu />
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

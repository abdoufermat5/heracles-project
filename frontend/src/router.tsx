import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Link,
  Outlet,
  redirect,
  type RouterHistory,
} from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/endpoints'
import { qk } from '@/api/hooks'
import { AppShell } from '@/components/shell/AppShell'
import { Button } from '@/components/ui/button'
import {
  LoginPage,
  RecoveryConfirmPage,
  RecoveryRequestPage,
  SecondFactorPage,
} from '@/features/auth/AuthPages'
import { DashboardPage } from '@/features/dashboard/DashboardPage'
import { ObjectEditor } from '@/features/editor/ObjectEditor'
import { ObjectListPage } from '@/features/listing/ObjectListPage'
import { MePage } from '@/features/me/MePage'

export interface RouterContext {
  queryClient: QueryClient
}

function NotFound() {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-center">
      <p className="text-lg font-semibold">{t('common.notFound')}</p>
      <Button asChild variant="outline">
        <Link to="/">{t('nav.dashboard')}</Link>
      </Button>
    </div>
  )
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
  notFoundComponent: NotFound,
})

/** Only same-origin absolute paths are accepted as post-login targets. */
function safeRedirect(v: unknown): string | undefined {
  return typeof v === 'string' && v.startsWith('/') && !v.startsWith('//') ? v : undefined
}

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  validateSearch: (s: Record<string, unknown>): { redirect?: string } => ({
    redirect: safeRedirect(s.redirect),
  }),
  component: LoginPage,
})

const secondFactorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login/second-factor',
  validateSearch: (s: Record<string, unknown>): { methods?: string; redirect?: string } => ({
    methods: typeof s.methods === 'string' ? s.methods : undefined,
    redirect: safeRedirect(s.redirect),
  }),
  component: SecondFactorPage,
})

const recoveryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/recovery',
  component: RecoveryRequestPage,
})

const recoveryConfirmRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/recovery/confirm',
  validateSearch: (s: Record<string, unknown>): { token?: string } => ({
    token: typeof s.token === 'string' ? s.token : undefined,
  }),
  component: RecoveryConfirmPage,
})

const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'app',
  beforeLoad: async ({ context, location }) => {
    try {
      await context.queryClient.ensureQueryData({ queryKey: qk.me, queryFn: api.me })
    } catch {
      throw redirect({ to: '/login', search: { redirect: location.href } })
    }
  },
  component: AppShell,
})

const dashboardRoute = createRoute({ getParentRoute: () => appRoute, path: '/', component: DashboardPage })
const meRoute = createRoute({ getParentRoute: () => appRoute, path: '/me', component: MePage })

const listRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type',
  component: function ListRoute() {
    const { type } = listRoute.useParams()
    return <ObjectListPage key={type} type={type} />
  },
})

const newRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type/new',
  component: function NewRoute() {
    const { type } = newRoute.useParams()
    return <ObjectEditor key={type} type={type} dn={null} />
  },
})

const editRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type/$dn',
  component: function EditRoute() {
    const { type, dn } = editRoute.useParams()
    return <ObjectEditor key={`${type}:${dn}`} type={type} dn={dn} />
  },
})

const routeTree = rootRoute.addChildren([
  loginRoute,
  secondFactorRoute,
  recoveryRoute,
  recoveryConfirmRoute,
  appRoute.addChildren([dashboardRoute, meRoute, listRoute, newRoute, editRoute]),
])

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    context: { queryClient },
    history,
    defaultPreload: 'intent',
    scrollRestoration: true,
  })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}

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
import type { ComponentType } from 'react'
import { Compass } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/endpoints'
import { qk } from '@/api/hooks'
import { WorkspaceShell } from '@/components/shell/WorkspaceShell'
import { adminApi } from '@/features/admin/api'
import { ak } from '@/features/admin/hooks'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import {
  LoginPage,
  RecoveryConfirmPage,
  RecoveryRequestPage,
  SecondFactorPage,
} from '@/features/auth/AuthPages'
import { DashboardPage } from '@/features/dashboard/DashboardPage'
import { ObjectEditor } from '@/features/editor/ObjectEditor'
import { TemplateEditorPage } from '@/features/editor/TemplateEditor'
import { ObjectListPage } from '@/features/listing/ObjectListPage'
import { CreateUserWizard } from '@/features/people/CreateUserWizard'
import { GroupProfilePage } from '@/features/people/GroupProfilePage'
import { UserProfilePage } from '@/features/people/UserProfilePage'
import { MePage } from '@/features/me/MePage'
import { StyleguidePage } from '@/features/styleguide/StyleguidePage'
import { AccessPage } from '@/features/admin/AccessPage'
import { AdminGate, type AdminCapability } from '@/features/admin/AdminGate'
import { ConfigPage } from '@/features/admin/ConfigPage'
import { HealthPage } from '@/features/admin/HealthPage'
import { PluginsPage } from '@/features/admin/PluginsPage'
import { TasksPage } from '@/features/admin/TasksPage'
import { IoPage } from '@/features/io/IoPage'

export interface RouterContext {
  queryClient: QueryClient
}

function NotFound() {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-[60vh] items-center justify-center p-6">
      <EmptyState
        icon={<Compass className="size-6 text-muted-foreground" aria-hidden />}
        title={t('common.notFound')}
        description={t('common.notFoundHelp', 'The requested page or directory object could not be found.')}
        action={
          <Button asChild variant="outline" size="sm" className="h-8">
            <Link to="/">{t('nav.dashboard')}</Link>
          </Button>
        }
        className="max-w-md w-full py-14"
      />
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
  validateSearch: (s: Record<string, unknown>): { redirect?: string; sso_error?: string } => ({
    redirect: safeRedirect(s.redirect),
    sso_error: s.sso_error === undefined ? undefined : String(s.sso_error),
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
  validateSearch: (s: Record<string, unknown>): { login?: string; token?: string } => ({
    login: typeof s.login === 'string' ? s.login : undefined,
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
    // decides between the administration console and the self-service portal
    try {
      await context.queryClient.ensureQueryData({
        queryKey: ak.caps,
        queryFn: adminApi.capabilities,
        staleTime: 60_000,
      })
    } catch {
      /* the shell falls back to the console; pages enforce their own rights */
    }
  },
  component: WorkspaceShell,
})

const dashboardRoute = createRoute({ getParentRoute: () => appRoute, path: '/', component: DashboardPage })
const meRoute = createRoute({ getParentRoute: () => appRoute, path: '/me', component: MePage })
// Living design reference; not linked from the navigation.
const styleguideRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/styleguide',
  component: StyleguidePage,
})

const listRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type',
  validateSearch: (
    s: Record<string, unknown>,
  ): { view?: 'templates'; filter?: 'active' | 'locked' | 'expiring' } => ({
    view: s.view === 'templates' ? 'templates' : undefined,
    filter:
      s.filter === 'active' || s.filter === 'locked' || s.filter === 'expiring' ? s.filter : undefined,
  }),
  component: function ListRoute() {
    const { type } = listRoute.useParams()
    const { view, filter } = listRoute.useSearch()
    return (
      <ObjectListPage
        key={`${type}:${filter ?? ''}`}
        type={type}
        view={view === 'templates' ? 'templates' : 'objects'}
        initialView={filter}
      />
    )
  },
})

const newRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type/new',
  validateSearch: (s: Record<string, unknown>): { copy?: string } => ({
    copy: typeof s.copy === 'string' && s.copy !== '' ? s.copy : undefined,
  }),
  component: function NewRoute() {
    const { type } = newRoute.useParams()
    const { copy } = newRoute.useSearch()
    if (type === 'user') {
      return <CreateUserWizard key={`user:${copy ?? ''}`} copyFrom={copy ?? null} />
    }
    return <ObjectEditor key={`${type}:${copy ?? ''}`} type={type} dn={null} copyFrom={copy ?? null} />
  },
})

// --- P3 objects ---
const templateNewRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type/templates/new',
  component: function TemplateNewRoute() {
    const { type } = templateNewRoute.useParams()
    return <TemplateEditorPage key={type} type={type} dn={null} />
  },
})

const templateEditRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type/templates/$dn',
  component: function TemplateEditRoute() {
    const { type, dn } = templateEditRoute.useParams()
    return <TemplateEditorPage key={`${type}:${dn}`} type={type} dn={dn} />
  },
})
// --- end P3 objects ---

const editRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type/$dn',
  validateSearch: (s: Record<string, unknown>): { view?: string; tab?: string } => ({
    view: typeof s.view === 'string' ? s.view : undefined,
    tab: typeof s.tab === 'string' ? s.tab : undefined,
  }),
  component: function EditRoute() {
    const { type, dn } = editRoute.useParams()
    const { view, tab } = editRoute.useSearch()
    if (type === 'user' && view !== 'generic') {
      return <UserProfilePage key={`user:${dn}`} dn={dn} />
    }
    if (type === 'group' && view !== 'generic') {
      return <GroupProfilePage key={`group:${dn}`} dn={dn} />
    }
    return <ObjectEditor key={`${type}:${dn}:${tab ?? ''}`} type={type} dn={dn} initialTab={tab} />
  },
})

// --- P3 admin ---
function adminRoute<P extends string>(path: P, capability: AdminCapability, Page: ComponentType) {
  return createRoute({
    getParentRoute: () => appRoute,
    path,
    component: () => (
      <AdminGate capability={capability}>
        <Page />
      </AdminGate>
    ),
  })
}
const adminAccessRoute = adminRoute('/admin/access', 'acl', AccessPage)
const adminConfigRoute = adminRoute('/admin/config', 'config', ConfigPage)
const adminHealthRoute = adminRoute('/admin/health', 'health', HealthPage)
const adminPluginsRoute = adminRoute('/admin/plugins', 'plugins', PluginsPage)
const adminTasksRoute = adminRoute('/admin/tasks', 'tasks', TasksPage)

// --- P3 compat ---
const ioRoute = createRoute({ getParentRoute: () => appRoute, path: '/io', component: IoPage })

const routeTree = rootRoute.addChildren([
  loginRoute,
  secondFactorRoute,
  recoveryRoute,
  recoveryConfirmRoute,
  appRoute.addChildren([
    dashboardRoute,
    meRoute,
    styleguideRoute,
    listRoute,
    newRoute,
    templateNewRoute,
    templateEditRoute,
    editRoute,
    ioRoute,
    adminAccessRoute,
    adminConfigRoute,
    adminHealthRoute,
    adminPluginsRoute,
    adminTasksRoute,
  ]),
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

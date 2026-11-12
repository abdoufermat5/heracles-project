import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Link,
  Outlet,
  redirect,
  type AsyncRouteComponent,
  type RouterHistory,
} from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { Compass } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import { qk } from '@/api/hooks'
import { WorkspaceShell } from '@/components/shell/WorkspaceShell'
import { adminApi } from '@/features/admin/api'
import { ak } from '@/features/admin/hooks'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { RouteError } from '@/components/resilience'
import { AdminGate, type AdminCapability } from '@/features/admin/AdminGate'
import { parseListSearch, type ListSearch } from '@/features/listing/urlState'

// Pages are split out of the entry bundle: the router loads a page's chunk before
// rendering its route, and on link intent (`defaultPreload`).
const SetupPage = lazyRouteComponent(() => import('@/features/setup/SetupWizard'), 'SetupPage')
const PublicFormPage = lazyRouteComponent(() => import('@/features/public/PublicFormPage'), 'PublicFormPage')
const authPages = () => import('@/features/auth/AuthPages')
const LoginPage = lazyRouteComponent(authPages, 'LoginPage')
const SecondFactorPage = lazyRouteComponent(authPages, 'SecondFactorPage')
const RecoveryRequestPage = lazyRouteComponent(authPages, 'RecoveryRequestPage')
const RecoveryConfirmPage = lazyRouteComponent(authPages, 'RecoveryConfirmPage')
const DashboardPage = lazyRouteComponent(() => import('@/features/dashboard/DashboardPage'), 'DashboardPage')
const ObjectEditor = lazyRouteComponent(() => import('@/features/editor/ObjectEditor'), 'ObjectEditor')
const TemplateEditorPage = lazyRouteComponent(
  () => import('@/features/editor/TemplateEditor'),
  'TemplateEditorPage',
)
const ObjectListPage = lazyRouteComponent(() => import('@/features/listing/ObjectListPage'), 'ObjectListPage')
const CreateUserWizard = lazyRouteComponent(() => import('@/features/people/CreateUserWizard'), 'CreateUserWizard')
const GroupProfilePage = lazyRouteComponent(() => import('@/features/people/GroupProfilePage'), 'GroupProfilePage')
const UserProfilePage = lazyRouteComponent(() => import('@/features/people/UserProfilePage'), 'UserProfilePage')
const MePage = lazyRouteComponent(() => import('@/features/me/MePage'), 'MePage')
const StyleguidePage = lazyRouteComponent(() => import('@/features/styleguide/StyleguidePage'), 'StyleguidePage')
const AccessPage = lazyRouteComponent(() => import('@/features/admin/AccessPage'), 'AccessPage')
const ConfigPage = lazyRouteComponent(() => import('@/features/admin/ConfigPage'), 'ConfigPage')
const HealthPage = lazyRouteComponent(() => import('@/features/admin/HealthPage'), 'HealthPage')
const PluginsPage = lazyRouteComponent(() => import('@/features/admin/PluginsPage'), 'PluginsPage')
const TasksPage = lazyRouteComponent(() => import('@/features/admin/TasksPage'), 'TasksPage')
const IoPage = lazyRouteComponent(() => import('@/features/io/IoPage'), 'IoPage')
const AuditPage = lazyRouteComponent(() => import('@/features/audit/AuditPage'), 'AuditPage')

/** A route component that renders lazy `pages`: preloading it preloads them. */
function rendering(
  component: () => ReactNode,
  ...pages: { preload?: () => Promise<void> | undefined }[]
): AsyncRouteComponent<object> {
  return Object.assign(component, {
    preload: async () => {
      await Promise.all(pages.map((page) => page.preload?.()))
    },
  })
}

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

// First-run setup: the server answers 503 `setup_required` everywhere else until it is done.
const setupRoute = createRoute({ getParentRoute: () => rootRoute, path: '/setup', component: SetupPage })

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  validateSearch: (s: Record<string, unknown>): { redirect?: string; sso_error?: string } => ({
    redirect: safeRedirect(s.redirect),
    sso_error: s.sso_error === undefined ? undefined : String(s.sso_error),
  }),
  component: LoginPage,
})

// Anonymous public form, and the registration page of an invitation link (`?token=`).
const publicFormRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/forms/$name',
  validateSearch: (s: Record<string, unknown>): { token?: string } => ({
    token: typeof s.token === 'string' && s.token ? s.token : undefined,
  }),
  component: PublicFormPage,
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
    } catch (e) {
      if (isApiError(e) && e.code === 'setup_required') throw redirect({ to: '/setup' })
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
  validateSearch: (s: Record<string, unknown>): ListSearch => parseListSearch(s),
  component: rendering(function ListRoute() {
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
  }, ObjectListPage),
})

const newRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type/new',
  validateSearch: (s: Record<string, unknown>): { copy?: string } => ({
    copy: typeof s.copy === 'string' && s.copy !== '' ? s.copy : undefined,
  }),
  component: rendering(
    function NewRoute() {
      const { type } = newRoute.useParams()
      const { copy } = newRoute.useSearch()
      if (type === 'user') {
        return <CreateUserWizard key={`user:${copy ?? ''}`} copyFrom={copy ?? null} />
      }
      return <ObjectEditor key={`${type}:${copy ?? ''}`} type={type} dn={null} copyFrom={copy ?? null} />
    },
    CreateUserWizard,
    ObjectEditor,
  ),
})

// --- P3 objects ---
const templateNewRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type/templates/new',
  component: rendering(function TemplateNewRoute() {
    const { type } = templateNewRoute.useParams()
    return <TemplateEditorPage key={type} type={type} dn={null} />
  }, TemplateEditorPage),
})

const templateEditRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type/templates/$dn',
  component: rendering(function TemplateEditRoute() {
    const { type, dn } = templateEditRoute.useParams()
    return <TemplateEditorPage key={`${type}:${dn}`} type={type} dn={dn} />
  }, TemplateEditorPage),
})
// --- end P3 objects ---

const editRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/types/$type/$dn',
  validateSearch: (s: Record<string, unknown>): { view?: string; tab?: string; edit?: boolean } => ({
    view: typeof s.view === 'string' ? s.view : undefined,
    tab: typeof s.tab === 'string' ? s.tab : undefined,
    edit: s.edit === true || s.edit === 'true' ? true : undefined,
  }),
  component: rendering(
    function EditRoute() {
      const { type, dn } = editRoute.useParams()
      const { view, tab, edit } = editRoute.useSearch()
      if (type === 'user' && view !== 'generic') {
        return <UserProfilePage key={`user:${dn}`} dn={dn} />
      }
      if (type === 'group' && view !== 'generic') {
        return <GroupProfilePage key={`group:${dn}`} dn={dn} />
      }
      return <ObjectEditor key={`${type}:${dn}:${tab ?? ''}`} type={type} dn={dn} initialTab={tab} autoEdit={edit} />
    },
    UserProfilePage,
    GroupProfilePage,
    ObjectEditor,
  ),
})

// --- P3 admin ---
function adminRoute<P extends string>(
  path: P,
  capability: AdminCapability,
  Page: AsyncRouteComponent<object>,
) {
  return createRoute({
    getParentRoute: () => appRoute,
    path,
    component: rendering(
      () => (
        <AdminGate capability={capability}>
          <Page />
        </AdminGate>
      ),
      Page,
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

// --- audit log ---
const auditRoute = createRoute({
  getParentRoute: () => appRoute,
  path: '/activity/audit',
  validateSearch: (s: Record<string, unknown>): { object?: string; actor?: string } => ({
    object: typeof s.object === 'string' && s.object !== '' ? s.object : undefined,
    actor: typeof s.actor === 'string' && s.actor !== '' ? s.actor : undefined,
  }),
  component: rendering(function AuditRoute() {
    const { object, actor } = auditRoute.useSearch()
    return <AuditPage key={`${object ?? ''}|${actor ?? ''}`} object={object} actor={actor} />
  }, AuditPage),
})

const routeTree = rootRoute.addChildren([
  setupRoute,
  loginRoute,
  publicFormRoute,
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
    auditRoute,
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
    defaultErrorComponent: RouteError,
    scrollRestoration: true,
  })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}

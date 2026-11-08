import { Link } from '@tanstack/react-router'
import {
  AlertTriangle,
  ArrowRight,
  Clock,
  ExternalLink,
  FolderTree,
  KeyRound,
  ListChecks,
  Lock,
  Plus,
  Server,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  UserPlus,
} from 'lucide-react'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useDashboard, useMe, useTypes } from '@/api/hooks'
import { ErrorState } from '@/components/ErrorState'
import { getRecentItems } from '@/components/shell/recent'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { TypeIcon } from '@/lib/icons'
import { useScope } from '@/lib/scope'
import { cn } from '@/lib/utils'

function resolveTypeRoute(cardKey: string): string {
  if (cardKey === 'departments') return 'department'
  if (cardKey === 'dns_zones') return 'dns_zone'
  return cardKey.replace(/s$/, '')
}

const CHART_COLORS = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--primary)',
]

export function DashboardPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = useDashboard()
  const { data: me } = useMe()
  const { data: types } = useTypes()
  const { base } = useScope()
  const recents = useMemo(() => getRecentItems(), [])

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />

  return (
    <div className="space-y-6">
      {/* Top Welcome Header */}
      <div className="flex flex-col gap-2 pb-4 border-b border-border/70 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            {t('dashboard.welcome', { name: me?.display_name ?? '' })}
          </h1>
          <p className="text-xs md:text-sm text-muted-foreground mt-0.5">
            {t('dashboard.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm" className="h-8 gap-1.5 text-xs">
            <Link to="/types/$type/new" params={{ type: 'user' }}>
              <UserPlus className="size-3.5 text-primary" />
              <span>{t('dashboard.createUser')}</span>
            </Link>
          </Button>
          <Button asChild variant="default" size="sm" className="h-8 gap-1.5 text-xs">
            <Link to="/types/$type" params={{ type: 'user' }}>
              <span>{t('dashboard.browseTree')}</span>
              <ArrowRight className="size-3.5" />
            </Link>
          </Button>
        </div>
      </div>

      {isPending ? (
        <div className="space-y-6" aria-busy="true" aria-label={t('common.loading')}>
          <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-5">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-24 w-full" />
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Skeleton className="h-72 lg:col-span-2" />
            <Skeleton className="h-72" />
          </div>
          <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
        </div>
      ) : (
        <>
          {/* Main Stat Tiles per Type */}
          <section aria-label={t('dashboard.overview')} className="space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {t('dashboard.overview')}
              </h2>
            </div>
            <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-5">
              {data.cards.map((c) => {
                const targetType = resolveTypeRoute(c.key)
                const typeMeta = types?.find((ty) => ty.name === targetType)
                const iconName = typeMeta?.icon ?? 'users'

                return (
                  <Link
                    key={c.key}
                    to="/types/$type"
                    params={{ type: targetType }}
                    className="group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-lg"
                  >
                    <Card className="p-4 transition-all hover:border-input hover:shadow-xs group-hover:bg-accent/30">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-medium text-muted-foreground truncate group-hover:text-foreground">
                          {c.label}
                        </span>
                        <div className="flex size-7 items-center justify-center rounded-md bg-muted/60 text-muted-foreground group-hover:bg-primary-soft group-hover:text-foreground transition-colors">
                          <TypeIcon name={iconName} className="size-3.5" />
                        </div>
                      </div>
                      <div className="mt-2.5 flex items-baseline justify-between">
                        <span className="text-2xl font-semibold tracking-tight text-foreground tabular-nums">
                          {c.value.toLocaleString()}
                        </span>
                        {c.trend !== null && c.trend !== 0 && (
                          <span
                            className={cn(
                              'flex items-center gap-0.5 text-[11px] font-medium tabular-nums',
                              c.trend > 0 ? 'text-success' : 'text-destructive',
                            )}
                          >
                            {c.trend > 0 ? (
                              <TrendingUp className="size-3" aria-hidden />
                            ) : (
                              <TrendingDown className="size-3" aria-hidden />
                            )}
                            <span>
                              {c.trend > 0 ? '+' : ''}
                              {c.trend}
                            </span>
                          </span>
                        )}
                      </div>
                    </Card>
                  </Link>
                )
              })}
            </div>
          </section>

          {/* Interactive Chart + System Information Side by Side */}
          <div className="grid gap-4 lg:grid-cols-3">
            {/* Objects by Type Chart */}
            <Card className="lg:col-span-2">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <div>
                  <CardTitle className="text-sm font-semibold">{t('dashboard.chartTitle')}</CardTitle>
                  <CardDescription className="text-xs mt-0.5">
                    {t('dashboard.overview')}
                  </CardDescription>
                </div>
                <Badge variant="outline" className="text-[11px] font-mono">
                  {data.cards.reduce((sum, c) => sum + c.value, 0).toLocaleString()} total
                </Badge>
              </CardHeader>
              <CardContent className="pt-2">
                <div className="h-60" role="img" aria-label={t('dashboard.chartTitle')}>
                  <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                    <BarChart
                      data={data.cards}
                      margin={{ top: 10, right: 12, left: -16, bottom: 0 }}
                    >
                      <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                      <XAxis
                        dataKey="label"
                        tickLine={false}
                        axisLine={false}
                        stroke="var(--muted-foreground)"
                        fontSize={11}
                      />
                      <YAxis
                        tickLine={false}
                        axisLine={false}
                        stroke="var(--muted-foreground)"
                        fontSize={11}
                        allowDecimals={false}
                      />
                      <Tooltip
                        cursor={{ fill: 'var(--accent)', opacity: 0.5 }}
                        contentStyle={{
                          backgroundColor: 'var(--popover)',
                          borderColor: 'var(--border)',
                          borderRadius: 'var(--radius)',
                          color: 'var(--popover-foreground)',
                          fontSize: '12px',
                          boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
                        }}
                      />
                      <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={48}>
                        {data.cards.map((_, index) => (
                          <Cell
                            key={`cell-${index}`}
                            fill={CHART_COLORS[index % CHART_COLORS.length]}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            {/* System / Directory Status Card */}
            <Card className="flex flex-col justify-between">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold">
                    {t('dashboard.systemInfo')}
                  </CardTitle>
                  <span className="flex items-center gap-1.5 text-xs text-success font-medium">
                    <span className="size-2 rounded-full bg-success animate-pulse" />
                    <span>{t('dashboard.connected')}</span>
                  </span>
                </div>
                <CardDescription className="text-xs">
                  {t('dashboard.connectionStatus')}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3.5 text-xs">
                <div className="space-y-1 rounded-md border border-border/80 bg-muted/40 p-2.5">
                  <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                    {t('dashboard.activeDirectory')}
                  </span>
                  <div className="flex items-center justify-between pt-0.5">
                    <span className="font-semibold text-foreground flex items-center gap-1.5">
                      <Server className="size-3.5 text-primary" />
                      <span>{me?.directory ?? 'Default LDAP'}</span>
                    </span>
                    <Badge variant="neutral" className="text-[10px]">
                      OpenLDAP
                    </Badge>
                  </div>
                </div>

                <div className="space-y-1 rounded-md border border-border/80 bg-muted/40 p-2.5">
                  <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                    {t('dashboard.activeScope')}
                  </span>
                  <p className="font-dn text-foreground truncate pt-0.5">
                    {base ?? me?.base ?? t('dashboard.globalScope')}
                  </p>
                </div>

                <div className="space-y-1 rounded-md border border-border/80 bg-muted/40 p-2.5">
                  <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                    {t('dashboard.currentUser')}
                  </span>
                  <div className="flex items-center justify-between pt-0.5">
                    <span className="font-medium text-foreground truncate">
                      {me?.display_name} ({me?.uid})
                    </span>
                    {me?.is_admin && (
                      <Badge variant="primary" className="text-[10px] gap-1">
                        <ShieldCheck className="size-2.5" />
                        <span>Admin</span>
                      </Badge>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Needs Attention Section */}
          <section aria-label={t('dashboard.attention')} className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {t('dashboard.attention')}
            </h2>
            <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
              <Link
                to="/types/$type"
                params={{ type: 'user' }}
                className="group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-lg"
              >
                <Card
                  className={cn(
                    'p-4 transition-all hover:border-input group-hover:bg-accent/30',
                    data.locked_users > 0 && 'border-warning/40 bg-warning/5',
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-muted-foreground">
                      {t('dashboard.lockedUsers')}
                    </span>
                    <div
                      className={cn(
                        'flex size-7 items-center justify-center rounded-md text-muted-foreground',
                        data.locked_users > 0
                          ? 'bg-warning/15 text-warning'
                          : 'bg-muted/60',
                      )}
                    >
                      <Lock className="size-3.5" aria-hidden />
                    </div>
                  </div>
                  <div className="mt-2.5 flex items-baseline justify-between">
                    <span
                      className={cn(
                        'text-2xl font-semibold tracking-tight tabular-nums',
                        data.locked_users > 0 ? 'text-warning' : 'text-foreground',
                      )}
                    >
                      {data.locked_users}
                    </span>
                    <span className="text-[11px] text-muted-foreground group-hover:text-foreground flex items-center gap-0.5">
                      <span>View</span>
                      <ArrowRight className="size-3" />
                    </span>
                  </div>
                </Card>
              </Link>

              <Card
                className={cn(
                  'p-4',
                  data.expiring_passwords > 0 && 'border-warning/40 bg-warning/5',
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">
                    {t('dashboard.expiringPasswords')}
                  </span>
                  <div
                    className={cn(
                      'flex size-7 items-center justify-center rounded-md text-muted-foreground',
                      data.expiring_passwords > 0
                        ? 'bg-warning/15 text-warning'
                        : 'bg-muted/60',
                    )}
                  >
                    <KeyRound className="size-3.5" aria-hidden />
                  </div>
                </div>
                <div className="mt-2.5">
                  <span
                    className={cn(
                      'text-2xl font-semibold tracking-tight tabular-nums',
                      data.expiring_passwords > 0 ? 'text-warning' : 'text-foreground',
                    )}
                  >
                    {data.expiring_passwords}
                  </span>
                </div>
              </Card>

              <Card className="p-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">
                    {t('dashboard.tasksPending')}
                  </span>
                  <div className="flex size-7 items-center justify-center rounded-md bg-muted/60 text-muted-foreground">
                    <ListChecks className="size-3.5" aria-hidden />
                  </div>
                </div>
                <div className="mt-2.5">
                  <span className="text-2xl font-semibold tracking-tight text-foreground tabular-nums">
                    {data.tasks.pending}
                  </span>
                </div>
              </Card>

              <Card
                className={cn(
                  'p-4',
                  data.tasks.failed > 0 && 'border-destructive/40 bg-destructive/5',
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">
                    {t('dashboard.tasksFailed')}
                  </span>
                  <div
                    className={cn(
                      'flex size-7 items-center justify-center rounded-md text-muted-foreground',
                      data.tasks.failed > 0
                        ? 'bg-destructive/15 text-destructive'
                        : 'bg-muted/60',
                    )}
                  >
                    <AlertTriangle className="size-3.5" aria-hidden />
                  </div>
                </div>
                <div className="mt-2.5">
                  <span
                    className={cn(
                      'text-2xl font-semibold tracking-tight tabular-nums',
                      data.tasks.failed > 0 ? 'text-destructive' : 'text-foreground',
                    )}
                  >
                    {data.tasks.failed}
                  </span>
                </div>
              </Card>
            </div>
          </section>

          {/* Quick Actions & Recently Viewed Objects */}
          <div className="grid gap-4 lg:grid-cols-3">
            {/* Quick Actions Panel */}
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold">
                  {t('dashboard.quickActions')}
                </CardTitle>
                <CardDescription className="text-xs">
                  Common directory management tasks
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <Button
                  asChild
                  variant="outline"
                  className="w-full justify-between h-8 text-xs font-normal"
                >
                  <Link to="/types/$type/new" params={{ type: 'user' }}>
                    <span className="flex items-center gap-2">
                      <UserPlus className="size-3.5 text-primary" />
                      <span>{t('dashboard.createUser')}</span>
                    </span>
                    <Plus className="size-3 text-muted-foreground" />
                  </Link>
                </Button>
                <Button
                  asChild
                  variant="outline"
                  className="w-full justify-between h-8 text-xs font-normal"
                >
                  <Link to="/types/$type/new" params={{ type: 'group' }}>
                    <span className="flex items-center gap-2">
                      <Plus className="size-3.5 text-primary" />
                      <span>{t('dashboard.createGroup')}</span>
                    </span>
                    <Plus className="size-3 text-muted-foreground" />
                  </Link>
                </Button>
                <Button
                  asChild
                  variant="outline"
                  className="w-full justify-between h-8 text-xs font-normal"
                >
                  <Link to="/types/$type" params={{ type: 'department' }}>
                    <span className="flex items-center gap-2">
                      <FolderTree className="size-3.5 text-primary" />
                      <span>{t('dashboard.browseTree')}</span>
                    </span>
                    <ArrowRight className="size-3 text-muted-foreground" />
                  </Link>
                </Button>
              </CardContent>
            </Card>

            {/* Recently Viewed Objects */}
            <Card className="lg:col-span-2">
              <CardHeader className="flex flex-row items-center justify-between pb-3">
                <div>
                  <CardTitle className="text-sm font-semibold">
                    {t('dashboard.recentObjects')}
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Objects you recently visited or edited
                  </CardDescription>
                </div>
                <Clock className="size-4 text-muted-foreground" aria-hidden />
              </CardHeader>
              <CardContent>
                {recents.length === 0 ? (
                  <EmptyState
                    icon={<Clock className="size-5" />}
                    title={t('dashboard.noRecentObjects')}
                    className="py-8"
                  />
                ) : (
                  <div className="space-y-1">
                    {recents.slice(0, 5).map((item) => (
                      <Link
                        key={item.dn}
                        to="/types/$type/$dn"
                        params={{ type: item.type, dn: item.dn }}
                        className="flex items-center justify-between rounded-md p-2 text-xs transition-colors hover:bg-muted/50"
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <TypeIcon name={item.type} className="size-3.5 text-muted-foreground shrink-0" />
                          <span className="font-medium text-foreground truncate">{item.title}</span>
                          <span className="font-dn text-muted-foreground/80 truncate text-[11px] max-w-[260px]">
                            {item.dn}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <Badge variant="outline" className="text-[10px] capitalize">
                            {item.type}
                          </Badge>
                          <ExternalLink className="size-3 text-muted-foreground/60" />
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}

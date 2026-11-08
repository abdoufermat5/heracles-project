import { Link } from '@tanstack/react-router'
import { ArrowRight, ChevronRight, Clock, ExternalLink } from 'lucide-react'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useDashboard, useMe } from '@/api/hooks'
import { ErrorState } from '@/components/ErrorState'
import { getRecentItems } from '@/components/shell/recent'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { PageHeader } from '@/components/ui/page-header'
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
  'var(--chart-5)',
] as const

const PANEL_HEADER = 'flex h-10 flex-row items-center justify-between border-b px-4 py-0'

export function DashboardPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = useDashboard()
  const { data: me } = useMe()
  const { base } = useScope()
  const recents = useMemo(() => getRecentItems(), [])

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />

  const total = data ? data.cards.reduce((sum, c) => sum + c.value, 0) : 0

  const attentionRows = data
    ? [
        {
          key: 'locked',
          label: t('dashboard.lockedUsers'),
          count: data.locked_users,
          dot: data.locked_users > 0 ? 'bg-warning' : undefined,
          type: 'user' as const,
        },
        {
          key: 'expiring',
          label: t('dashboard.expiringPasswords'),
          count: data.expiring_passwords,
          dot: data.expiring_passwords > 0 ? 'bg-warning' : undefined,
          type: undefined,
        },
        {
          key: 'pending',
          label: t('dashboard.tasksPending'),
          count: data.tasks.pending,
          dot: undefined,
          type: undefined,
        },
        {
          key: 'failed',
          label: t('dashboard.tasksFailed'),
          count: data.tasks.failed,
          dot: data.tasks.failed > 0 ? 'bg-destructive' : undefined,
          type: undefined,
        },
      ]
    : []

  return (
    <div className="space-y-4">
      <PageHeader
        title={t('dashboard.title')}
        description={
          <span className="flex flex-wrap items-center gap-1.5">
            <span>{me?.directory ?? t('dashboard.defaultDirectory')}</span>
            <span aria-hidden="true">·</span>
            <span className="font-mono">{base ?? me?.base ?? t('dashboard.globalScope')}</span>
          </span>
        }
        actions={
          <>
            <Button asChild variant="outline" size="sm">
              <Link to="/types/$type/new" params={{ type: 'user' }}>
                {t('dashboard.createUser')}
              </Link>
            </Button>
            <Button asChild size="sm">
              <Link to="/types/$type" params={{ type: 'user' }}>
                {t('dashboard.browseTree')}
              </Link>
            </Button>
          </>
        }
      />

      {isPending || !data ? (
        <div className="space-y-4" aria-busy="true" aria-label={t('common.loading')}>
          <Skeleton className="h-[92px] w-full" />
          <div className="grid gap-4 lg:grid-cols-3">
            <Skeleton className="h-64 lg:col-span-2" />
            <Skeleton className="h-64" />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Skeleton className="h-56" />
            <Skeleton className="h-56" />
          </div>
        </div>
      ) : (
        <>
          {/* Metrics: one panel, hairline-separated cells */}
          <Card className="overflow-hidden py-0" role="group" aria-label={t('dashboard.overview')}>
            <div className="flex flex-wrap gap-px bg-border">
              {data.cards.map((c) => {
                const targetType = resolveTypeRoute(c.key)
                return (
                  <Link
                    key={c.key}
                    to="/types/$type"
                    params={{ type: targetType }}
                    className="group min-w-40 flex-1 bg-card p-4 transition-colors hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  >
                    <span className="label-caps block truncate">{c.label}</span>
                    <span className="mt-2 flex items-baseline justify-between gap-2">
                      <span className="text-2xl font-semibold tabular-nums text-foreground">
                        {c.value.toLocaleString()}
                      </span>
                      {c.trend !== null && c.trend !== 0 && (
                        <span
                          className={cn(
                            'text-xs tabular-nums',
                            c.trend > 0 ? 'text-success' : 'text-destructive',
                          )}
                        >
                          {c.trend > 0 ? '+' : ''}
                          {c.trend}
                        </span>
                      )}
                    </span>
                  </Link>
                )
              })}
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-3">
            {/* Composition */}
            <Card className="lg:col-span-2">
              <CardHeader className={PANEL_HEADER}>
                <CardTitle className="text-[13px] font-semibold">
                  {t('dashboard.composition')}
                </CardTitle>
                <span className="font-mono text-xs tabular-nums text-muted-foreground">
                  {total.toLocaleString()} {t('dashboard.objects')}
                </span>
              </CardHeader>
              <CardContent className="p-4">
                <div
                  className="flex h-2 w-full gap-px overflow-hidden rounded-sm bg-muted"
                  role="img"
                  aria-label={t('dashboard.composition')}
                >
                  {data.cards.map((c, index) => {
                    if (c.value === 0 || total === 0) return null
                    return (
                      <div
                        key={c.key}
                        className="h-full"
                        style={{
                          width: `${(c.value / total) * 100}%`,
                          backgroundColor: CHART_COLORS[index % CHART_COLORS.length],
                        }}
                      />
                    )
                  })}
                </div>

                <table className="mt-3 w-full text-[13px]">
                  <tbody className="divide-y">
                    {data.cards.map((c, index) => (
                      <tr key={c.key}>
                        <td className="py-2">
                          <span className="flex items-center gap-2">
                            <span
                              className="size-2 shrink-0 rounded-[1px]"
                              style={{ backgroundColor: CHART_COLORS[index % CHART_COLORS.length] }}
                              aria-hidden="true"
                            />
                            <span className="truncate text-foreground">{c.label}</span>
                          </span>
                        </td>
                        <td className="py-2 text-right font-mono tabular-nums text-foreground">
                          {c.value.toLocaleString()}
                        </td>
                        <td className="w-16 py-2 text-right tabular-nums text-muted-foreground">
                          {total > 0 ? `${((c.value / total) * 100).toFixed(1)}%` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>

            {/* Directory status */}
            <Card>
              <CardHeader className={PANEL_HEADER}>
                <CardTitle className="text-[13px] font-semibold">
                  {t('dashboard.systemInfo')}
                </CardTitle>
                <span className="flex items-center gap-1.5 text-xs text-success">
                  <span className="size-1.5 rounded-full bg-success" aria-hidden="true" />
                  {t('dashboard.connected')}
                </span>
              </CardHeader>
              <CardContent className="p-4">
                <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 text-[13px]">
                  <dt className="label-caps pt-0.5">{t('dashboard.activeDirectory')}</dt>
                  <dd className="truncate font-mono text-foreground">
                    {me?.directory ?? t('dashboard.defaultDirectory')}
                  </dd>

                  <dt className="label-caps pt-0.5">{t('dashboard.activeScope')}</dt>
                  <dd className="break-all font-dn text-foreground">
                    {base ?? me?.base ?? t('dashboard.globalScope')}
                  </dd>

                  <dt className="label-caps pt-0.5">{t('dashboard.currentUser')}</dt>
                  <dd className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-foreground">{me?.display_name}</span>
                    <Badge variant="neutral" className="shrink-0">
                      {me?.is_admin ? t('me.admin') : t('me.operator')}
                    </Badge>
                  </dd>
                </dl>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Needs attention */}
            <Card className="overflow-hidden" role="region" aria-label={t('dashboard.attention')}>
              <CardHeader className={PANEL_HEADER}>
                <CardTitle className="text-[13px] font-semibold">
                  {t('dashboard.attention')}
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <ul className="divide-y">
                  {attentionRows.map((row) => (
                    <li key={row.key} className="flex h-9 items-center gap-2 px-4 text-[13px]">
                      {row.dot ? (
                        <span className={cn('size-1.5 shrink-0 rounded-full', row.dot)} aria-hidden="true" />
                      ) : (
                        <span className="size-1.5 shrink-0" aria-hidden="true" />
                      )}
                      <span
                        className={cn(
                          'flex-1 truncate',
                          row.count > 0 ? 'text-foreground' : 'text-muted-foreground',
                        )}
                      >
                        {row.label}
                      </span>
                      <span
                        className={cn(
                          'font-mono tabular-nums',
                          row.count > 0 ? 'text-foreground' : 'text-muted-foreground',
                        )}
                      >
                        {row.count}
                      </span>
                      {row.type ? (
                        <Link
                          to="/types/$type"
                          params={{ type: row.type }}
                          className="ml-1 flex items-center gap-0.5 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                        >
                          {t('dashboard.view')}
                          <ChevronRight className="size-3.5" aria-hidden="true" />
                        </Link>
                      ) : (
                        <span className="ml-1 w-[46px]" aria-hidden="true" />
                      )}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>

            {/* Quick actions */}
            <Card className="overflow-hidden">
              <CardHeader className={PANEL_HEADER}>
                <CardTitle className="text-[13px] font-semibold">
                  {t('dashboard.quickActions')}
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <ul className="divide-y">
                  <li>
                    <Link
                      to="/types/$type/new"
                      params={{ type: 'user' }}
                      className="flex h-9 items-center justify-between px-4 text-[13px] text-foreground transition-colors hover:bg-accent/40"
                    >
                      {t('dashboard.createUser')}
                      <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
                    </Link>
                  </li>
                  <li>
                    <Link
                      to="/types/$type/new"
                      params={{ type: 'group' }}
                      className="flex h-9 items-center justify-between px-4 text-[13px] text-foreground transition-colors hover:bg-accent/40"
                    >
                      {t('dashboard.createGroup')}
                      <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
                    </Link>
                  </li>
                  <li>
                    <Link
                      to="/types/$type"
                      params={{ type: 'department' }}
                      className="flex h-9 items-center justify-between px-4 text-[13px] text-foreground transition-colors hover:bg-accent/40"
                    >
                      {t('dashboard.browseTree')}
                      <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden="true" />
                    </Link>
                  </li>
                </ul>
              </CardContent>
            </Card>
          </div>

          {/* Recently viewed objects */}
          <Card className="overflow-hidden">
            <CardHeader className={PANEL_HEADER}>
              <CardTitle className="text-[13px] font-semibold">
                {t('dashboard.recentObjects')}
              </CardTitle>
              <Clock className="size-4 text-muted-foreground" aria-hidden="true" />
            </CardHeader>
            <CardContent className="p-0">
              {recents.length === 0 ? (
                <EmptyState
                  icon={<Clock className="size-5" />}
                  title={t('dashboard.noRecentObjects')}
                  className="py-8"
                />
              ) : (
                <ul className="divide-y">
                  {recents.slice(0, 5).map((item) => (
                    <li key={item.dn}>
                      <Link
                        to="/types/$type/$dn"
                        params={{ type: item.type, dn: item.dn }}
                        className="flex h-9 items-center justify-between gap-3 px-4 text-[13px] transition-colors hover:bg-accent/40"
                      >
                        <span className="flex min-w-0 items-center gap-2.5">
                          <TypeIcon name={item.type} className="size-3.5 shrink-0 text-muted-foreground" />
                          <span className="truncate font-medium text-foreground">{item.title}</span>
                          <span className="truncate font-dn text-muted-foreground">{item.dn}</span>
                        </span>
                        <span className="flex shrink-0 items-center gap-2">
                          <Badge variant="neutral">{item.type}</Badge>
                          <ExternalLink className="size-3 text-muted-foreground" aria-hidden="true" />
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

import { Link } from '@tanstack/react-router'
import { AlertTriangle, KeyRound, ListChecks, Lock, TrendingDown, TrendingUp } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useDashboard, useMe } from '@/api/hooks'
import { ErrorState } from '@/components/ErrorState'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

function Stat({
  icon,
  label,
  value,
  tone,
  to,
}: {
  icon: React.ReactNode
  label: string
  value: React.ReactNode
  tone?: 'warn'
  to?: string
}) {
  const body = (
    <div className="flex items-center gap-3">
      <div
        className={
          tone === 'warn'
            ? 'bg-warning/15 text-warning flex size-9 items-center justify-center rounded-lg'
            : 'bg-primary-soft text-primary flex size-9 items-center justify-center rounded-lg'
        }
      >
        {icon}
      </div>
      <div>
        <p className="text-xl leading-none font-semibold tabular-nums">{value}</p>
        <p className="text-muted-foreground mt-1 text-xs">{label}</p>
      </div>
    </div>
  )
  return <Card className="p-4">{to ? <Link to={to}>{body}</Link> : body}</Card>
}

export function DashboardPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = useDashboard()
  const { data: me } = useMe()

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">
          {t('dashboard.welcome', { name: me?.display_name ?? '' })}
        </h1>
        <p className="text-muted-foreground text-sm">{t('dashboard.subtitle')}</p>
      </div>

      {isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-busy="true" aria-label={t('common.loading')}>
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : (
        <>
          <section aria-label={t('dashboard.overview')} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            {data.cards.map((c) => (
              <Card key={c.key}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-muted-foreground text-xs font-medium">{c.label}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-2xl font-semibold tabular-nums">{c.value.toLocaleString()}</p>
                  {c.trend !== null && c.trend !== 0 && (
                    <p
                      className={
                        c.trend > 0
                          ? 'text-success mt-1 flex items-center gap-1 text-xs'
                          : 'text-destructive mt-1 flex items-center gap-1 text-xs'
                      }
                    >
                      {c.trend > 0 ? <TrendingUp className="size-3" aria-hidden /> : <TrendingDown className="size-3" aria-hidden />}
                      {c.trend > 0 ? '+' : ''}
                      {c.trend}
                    </p>
                  )}
                </CardContent>
              </Card>
            ))}
          </section>

          <section aria-label={t('dashboard.attention')} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              icon={<Lock className="size-4" />}
              label={t('dashboard.lockedUsers')}
              value={data.locked_users}
              tone={data.locked_users > 0 ? 'warn' : undefined}
              to="/types/user"
            />
            <Stat
              icon={<KeyRound className="size-4" />}
              label={t('dashboard.expiringPasswords')}
              value={data.expiring_passwords}
              tone={data.expiring_passwords > 0 ? 'warn' : undefined}
            />
            <Stat icon={<ListChecks className="size-4" />} label={t('dashboard.tasksPending')} value={data.tasks.pending} />
            <Stat
              icon={<AlertTriangle className="size-4" />}
              label={t('dashboard.tasksFailed')}
              value={data.tasks.failed}
              tone={data.tasks.failed > 0 ? 'warn' : undefined}
            />
          </section>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">{t('dashboard.chartTitle')}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-56" role="img" aria-label={t('dashboard.chartTitle')}>
                <ResponsiveContainer width="100%" height="100%" minWidth={0}>
                  <BarChart data={data.cards} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke="var(--border)" />
                    <XAxis dataKey="label" tickLine={false} axisLine={false} stroke="var(--muted-foreground)" fontSize={12} />
                    <YAxis tickLine={false} axisLine={false} stroke="var(--muted-foreground)" fontSize={12} allowDecimals={false} />
                    <Tooltip
                      cursor={{ fill: 'var(--accent)' }}
                      contentStyle={{
                        background: 'var(--popover)',
                        border: '1px solid var(--border)',
                        borderRadius: 8,
                        color: 'var(--popover-foreground)',
                      }}
                    />
                    <Bar dataKey="value" fill="var(--chart-1)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

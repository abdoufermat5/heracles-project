import { Link } from '@tanstack/react-router'
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  KeyRound,
  ListChecks,
  Lock,
  TriangleAlert,
  Upload,
  UserPlus,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useDashboard, useMe, useTypes } from '@/api/hooks'
import { ErrorState } from '@/components/ErrorState'
import { getRecentItems } from '@/components/shell/recent'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useCapabilities } from '@/features/admin/hooks'
import { useIoAccess } from '@/features/io/hooks'
import { TypeIcon } from '@/lib/icons'
import { cn } from '@/lib/utils'

/** Dashboard card keys are plural ("users", "dns_zones"); routes use the type name. */
function typeOfCard(cardKey: string): string {
  if (cardKey === 'departments') return 'department'
  if (cardKey === 'dns_zones') return 'dns_zone'
  return cardKey.replace(/s$/, '')
}

function greetingKey(hour: number): 'morning' | 'afternoon' | 'evening' {
  if (hour < 12) return 'morning'
  if (hour < 18) return 'afternoon'
  return 'evening'
}

type Tone = 'warning' | 'danger' | 'neutral'

const TONE: Record<Tone, string> = {
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-destructive-soft text-destructive',
  neutral: 'bg-muted text-muted-foreground',
}

/** One item of the work queue: what needs doing, how many, and where to do it. */
function QueueItem({
  icon: Icon,
  tone,
  count,
  title,
  description,
  action,
}: {
  icon: LucideIcon
  tone: Tone
  count: number
  title: string
  description: string
  action?: React.ReactNode
}) {
  return (
    <li className="flex items-center gap-4 px-5 py-4">
      <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-lg', TONE[tone])}>
        <Icon className="size-5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-body font-medium text-foreground">
          <span className="tabular-nums">{count.toLocaleString()}</span> {title}
        </p>
        <p className="text-small text-muted-foreground">{description}</p>
      </div>
      {action}
    </li>
  )
}

function QuickAction({
  icon: Icon,
  label,
  description,
  children,
}: {
  icon: LucideIcon
  label: string
  description: string
  children: (content: React.ReactNode) => React.ReactNode
}) {
  return children(
    <span className="flex h-full items-start gap-3 rounded-lg border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-primary-soft/40">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary-soft text-primary">
        <Icon className="size-4.5" aria-hidden />
      </span>
      <span className="min-w-0">
        <span className="block text-body font-medium text-foreground">{label}</span>
        <span className="block text-small text-muted-foreground">{description}</span>
      </span>
    </span>,
  )
}

export function DashboardPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = useDashboard()
  const { data: me } = useMe()
  const { data: types } = useTypes()
  const { data: caps } = useCapabilities()
  const { data: io } = useIoAccess()
  const recents = useMemo(() => getRecentItems(), [])

  const canCreate = (name: string) => !!types?.find((x) => x.name === name)?.can_create
  const firstName = (me?.display_name ?? '').split(/\s+/)[0] || me?.uid || ''
  const greeting = t(`dashboard.greeting_${greetingKey(new Date().getHours())}`, { name: firstName })

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />

  const locked = data?.locked_users ?? 0
  const expiring = data?.expiring_passwords ?? 0
  const failed = data?.tasks.failed ?? 0
  const pending = data?.tasks.pending ?? 0
  const queueEmpty = !isPending && locked + expiring + failed === 0

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1">
          <h1 className="text-title font-semibold tracking-tight text-foreground">{greeting}</h1>
          <p className="text-body text-muted-foreground">{t('dashboard.subtitle')}</p>
        </div>
        <div className="flex gap-2">
          <Button asChild variant="outline">
            <Link to="/types/$type" params={{ type: 'user' }}>
              <Users />
              {t('dashboard.browsePeople')}
            </Link>
          </Button>
          {canCreate('user') && (
            <Button asChild>
              <Link to="/types/$type/new" params={{ type: 'user' }}>
                <UserPlus />
                {t('dashboard.createUser')}
              </Link>
            </Button>
          )}
        </div>
      </header>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section aria-labelledby="queue-title" className="rounded-lg border bg-card">
          <div className="flex items-center justify-between border-b px-5 py-3.5">
            <h2 id="queue-title" className="text-body font-semibold text-foreground">
              {t('dashboard.attention')}
            </h2>
            {pending > 0 && (
              <span className="text-small text-muted-foreground">
                {t('dashboard.pendingTasks', { count: pending })}
              </span>
            )}
          </div>
          {isPending ? (
            <div className="space-y-3 p-5">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : queueEmpty ? (
            <div className="flex items-center gap-4 px-5 py-8">
              <span className="flex size-10 items-center justify-center rounded-lg bg-success-soft text-success">
                <CheckCircle2 className="size-5" aria-hidden />
              </span>
              <div>
                <p className="text-body font-medium text-foreground">{t('dashboard.allClear')}</p>
                <p className="text-small text-muted-foreground">{t('dashboard.allClearHelp')}</p>
              </div>
            </div>
          ) : (
            <ul className="divide-y">
              {locked > 0 && (
                <QueueItem
                  icon={Lock}
                  tone="warning"
                  count={locked}
                  title={t('dashboard.lockedTitle', { count: locked })}
                  description={t('dashboard.lockedHelp')}
                  action={
                    <Button asChild variant="outline" size="sm">
                      <Link to="/types/$type" params={{ type: 'user' }}>
                        {t('dashboard.review')}
                        <ArrowRight />
                      </Link>
                    </Button>
                  }
                />
              )}
              {expiring > 0 && (
                <QueueItem
                  icon={KeyRound}
                  tone="warning"
                  count={expiring}
                  title={t('dashboard.expiringTitle', { count: expiring })}
                  description={t('dashboard.expiringHelp')}
                  action={
                    <Button asChild variant="outline" size="sm">
                      <Link to="/types/$type" params={{ type: 'user' }}>
                        {t('dashboard.review')}
                        <ArrowRight />
                      </Link>
                    </Button>
                  }
                />
              )}
              {failed > 0 && (
                <QueueItem
                  icon={TriangleAlert}
                  tone="danger"
                  count={failed}
                  title={t('dashboard.failedTitle', { count: failed })}
                  description={t('dashboard.failedHelp')}
                  action={
                    caps?.tasks ? (
                      <Button asChild variant="outline" size="sm">
                        <Link to="/admin/tasks">
                          {t('dashboard.review')}
                          <ArrowRight />
                        </Link>
                      </Button>
                    ) : undefined
                  }
                />
              )}
            </ul>
          )}
        </section>

        <section aria-labelledby="recent-title" className="rounded-lg border bg-card">
          <div className="flex items-center justify-between border-b px-5 py-3.5">
            <h2 id="recent-title" className="text-body font-semibold text-foreground">
              {t('dashboard.recentObjects')}
            </h2>
            <Clock className="size-4 text-muted-foreground" aria-hidden />
          </div>
          {recents.length === 0 ? (
            <p className="px-5 py-8 text-small text-muted-foreground">{t('dashboard.noRecentObjects')}</p>
          ) : (
            <ul className="divide-y">
              {recents.slice(0, 6).map((r) => (
                <li key={r.dn}>
                  <Link
                    to="/types/$type/$dn"
                    params={{ type: r.type, dn: r.dn }}
                    className="flex items-center gap-3 px-5 py-2.5 hover:bg-muted/50"
                  >
                    <TypeIcon
                      name={types?.find((x) => x.name === r.type)?.icon ?? 'file'}
                      className="size-4 shrink-0 text-muted-foreground"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-body text-foreground">{r.title}</span>
                      {r.subtitle && (
                        <span className="block truncate text-small text-muted-foreground">{r.subtitle}</span>
                      )}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section aria-labelledby="actions-title" className="space-y-3">
        <h2 id="actions-title" className="label-caps">
          {t('dashboard.quickActions')}
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {canCreate('user') && (
            <QuickAction icon={UserPlus} label={t('dashboard.createUser')} description={t('dashboard.createUserHelp')}>
              {(c) => (
                <Link to="/types/$type/new" params={{ type: 'user' }} className="rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  {c}
                </Link>
              )}
            </QuickAction>
          )}
          {canCreate('group') && (
            <QuickAction icon={Users} label={t('dashboard.createGroup')} description={t('dashboard.createGroupHelp')}>
              {(c) => (
                <Link to="/types/$type/new" params={{ type: 'group' }} className="rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  {c}
                </Link>
              )}
            </QuickAction>
          )}
          {io?.csv_import && (
            <QuickAction icon={Upload} label={t('dashboard.import')} description={t('dashboard.importHelp')}>
              {(c) => (
                <Link to="/io" className="rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  {c}
                </Link>
              )}
            </QuickAction>
          )}
          {caps?.acl && (
            <QuickAction icon={ListChecks} label={t('dashboard.checkRights')} description={t('dashboard.checkRightsHelp')}>
              {(c) => (
                <Link to="/admin/access" className="rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  {c}
                </Link>
              )}
            </QuickAction>
          )}
        </div>
      </section>

      <section aria-labelledby="counts-title" className="space-y-3">
        <h2 id="counts-title" className="label-caps">
          {t('dashboard.overview')}
        </h2>
        {isPending ? (
          <Skeleton className="h-20 w-full" />
        ) : (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {(data?.cards ?? []).map((c) => (
              <li key={c.key}>
                <Link
                  to="/types/$type"
                  params={{ type: typeOfCard(c.key) }}
                  className="block rounded-lg border bg-card px-4 py-3 hover:border-primary/40"
                >
                  <span className="block text-small text-muted-foreground">{c.label}</span>
                  <span className="mt-0.5 flex items-baseline gap-2">
                    <span className="text-title font-semibold tabular-nums text-foreground">
                      {c.value.toLocaleString()}
                    </span>
                    {c.trend ? (
                      <span className={cn('text-caption tabular-nums', c.trend > 0 ? 'text-success' : 'text-muted-foreground')}>
                        {c.trend > 0 ? `+${c.trend}` : c.trend}
                      </span>
                    ) : null}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

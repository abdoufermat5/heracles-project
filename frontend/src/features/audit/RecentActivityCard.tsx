import { Link } from '@tanstack/react-router'
import { ArrowRight, ScrollText } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ActionBadge } from './EventParts'
import { formatRelative } from './format'
import { useAuditEnabled, useAuditEvents } from './hooks'

/** Dashboard card: the latest events of the audit log. Hidden without the plugin or the right. */
export function RecentActivityCard() {
  const { t } = useTranslation()
  const { enabled } = useAuditEnabled()
  const list = useAuditEvents({ limit: 5 }, enabled)
  if (!enabled || list.isError) return null
  const events = list.data?.pages.flatMap((p) => p.items).slice(0, 5) ?? []

  return (
    <section aria-labelledby="activity-title" className="rounded-lg border bg-card">
      <div className="flex items-center justify-between border-b px-5 py-3.5">
        <h2 id="activity-title" className="text-body font-semibold text-foreground">
          {t('audit.recent.title')}
        </h2>
        <Button asChild variant="ghost" size="sm">
          <Link to="/activity/audit">
            {t('audit.recent.viewAll')}
            <ArrowRight aria-hidden />
          </Link>
        </Button>
      </div>
      {list.isPending ? (
        <div className="space-y-2 p-5" aria-busy="true" aria-label={t('common.loading')}>
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : events.length === 0 ? (
        <p className="px-5 py-8 text-small text-muted-foreground">{t('audit.recent.empty')}</p>
      ) : (
        <ul className="divide-y">
          {events.map((e) => (
            <li key={e.dn} className="flex items-center gap-3 px-5 py-2.5">
              <ScrollText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <ActionBadge event={e} />
              <span className="min-w-0 flex-1 truncate text-body text-foreground">
                {e.object.label || e.object.dn}
                {e.actor.label && (
                  <span className="text-muted-foreground"> {t('audit.history.by', { actor: e.actor.label })}</span>
                )}
              </span>
              <time dateTime={e.time} className="shrink-0 text-small text-muted-foreground">
                {formatRelative(e.time)}
              </time>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

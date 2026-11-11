import { Link } from '@tanstack/react-router'
import { ScrollText } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ErrorState } from '@/components/ErrorState'
import { SectionCard } from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ActionBadge, WhenCell } from './EventParts'
import { useAuditEnabled, useAuditEvents } from './hooks'
import { CHANGE_ACTIONS, SIGN_IN_ACTIONS, type AuditEvent } from './types'

export type HistoryKind = 'all' | 'signins' | 'changes'

const KIND_ACTIONS: Record<HistoryKind, string[] | undefined> = {
  all: undefined,
  signins: SIGN_IN_ACTIONS,
  changes: CHANGE_ACTIONS,
}

function summary(e: AuditEvent): string {
  return e.attributes.slice(0, 2).join(' · ')
}

/**
 * Events recorded about one directory object, newest first. Renders nothing when the audit
 * plugin is not enabled; a user without the right to read the log sees an explanation instead.
 */
export function ObjectHistory({
  dn,
  kind = 'all',
  limit = 10,
  title,
  help,
  emptyText,
  bare = false,
}: {
  dn: string
  kind?: HistoryKind
  limit?: number
  title?: string
  help?: string
  emptyText?: string
  /** Render the list without its card (the caller provides the frame). */
  bare?: boolean
}) {
  const { t } = useTranslation()
  const { enabled } = useAuditEnabled()
  const list = useAuditEvents({ object: dn, action: KIND_ACTIONS[kind], limit }, enabled)
  if (!enabled) return null

  const events = list.data?.pages.flatMap((p) => p.items).slice(0, limit) ?? []
  const body = list.isError ? (
    <ErrorState error={list.error} onRetry={() => void list.refetch()} />
  ) : list.isPending ? (
    <div className="space-y-2" aria-busy="true" aria-label={t('common.loading')}>
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-3/4" />
    </div>
  ) : events.length === 0 ? (
    <p className="py-4 text-small text-muted-foreground">{emptyText ?? t('audit.history.empty')}</p>
  ) : (
    <ul className="divide-y" aria-label={title ?? t('audit.history.title')}>
      {events.map((e) => (
        <li key={e.dn} className="flex items-start gap-4 py-2.5">
          <div className="w-44 shrink-0">
            <WhenCell iso={e.time} />
          </div>
          <div className="min-w-0 flex-1 space-y-0.5">
            <div className="flex flex-wrap items-center gap-2">
              <ActionBadge event={e} />
              {e.actor.label && (
                <span className="text-small text-muted-foreground">
                  {t('audit.history.by', { actor: e.actor.label })}
                </span>
              )}
              {e.ip && <span className="font-dn text-caption text-muted-foreground">{e.ip}</span>}
            </div>
            {summary(e) && <p className="truncate font-dn text-caption text-muted-foreground">{summary(e)}</p>}
          </div>
        </li>
      ))}
    </ul>
  )
  const link = (
    <Button asChild variant="ghost" size="sm">
      <Link to="/activity/audit" search={{ object: dn }}>
        <ScrollText aria-hidden />
        {t('audit.history.viewAll')}
      </Link>
    </Button>
  )

  if (bare) return body
  return (
    <SectionCard
      title={title ?? t('audit.history.title')}
      description={help ?? t('audit.history.help')}
      actions={link}
    >
      {body}
    </SectionCard>
  )
}

/** Security tab of a person: recent sign-ins and recent changes. */
export function UserActivity({ dn }: { dn: string }) {
  const { t } = useTranslation()
  return (
    <>
      <ObjectHistory
        dn={dn}
        kind="signins"
        limit={5}
        title={t('audit.history.signIns')}
        help={t('audit.history.signInsHelp')}
        emptyText={t('audit.history.signInsEmpty')}
      />
      <ObjectHistory
        dn={dn}
        kind="changes"
        limit={5}
        title={t('audit.history.changes')}
        help={t('audit.history.changesHelp')}
        emptyText={t('audit.history.changesEmpty')}
      />
    </>
  )
}

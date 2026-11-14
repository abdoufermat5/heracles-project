import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { useTypes } from '@/api/hooks'
import { Badge } from '@/components/ui/badge'
import { typeLabel as translatedTypeLabel } from '@/lib/labels'
import { cn } from '@/lib/utils'
import { actionTone, formatAbsolute, formatRelative, parseAttribute } from './format'
import type { AuditEvent } from './types'

export function ActionBadge({ event }: { event: Pick<AuditEvent, 'action' | 'result'> }) {
  const { t } = useTranslation()
  const label = t(`audit.actions.${event.action}`, { defaultValue: event.action })
  return (
    <span className="inline-flex items-center gap-1.5">
      <Badge variant={actionTone(event)}>{label}</Badge>
      {event.result === 'failure' && event.action !== 'login_failed' && (
        <Badge variant="destructive">{t('audit.results.failure')}</Badge>
      )}
    </span>
  )
}

/** Relative time with the exact date as secondary text. */
export function WhenCell({ iso, className }: { iso: string; className?: string }) {
  return (
    <time dateTime={iso} title={formatAbsolute(iso)} className={cn('block', className)}>
      <span className="block text-body text-foreground">{formatRelative(iso)}</span>
      <span className="block text-caption text-muted-foreground">{formatAbsolute(iso)}</span>
    </time>
  )
}

/** The author: readable label first, DN secondary. */
export function ActorChip({ actor }: { actor: AuditEvent['actor'] }) {
  const { t } = useTranslation()
  const label = actor.label || t('audit.actor.unknown')
  return (
    <span className="block min-w-0">
      {actor.dn ? (
        <Link
          to="/types/$type/$dn"
          params={{ type: 'user', dn: actor.dn }}
          className="inline-flex max-w-full items-center rounded-full border bg-muted/50 px-2 py-0.5 text-small font-medium text-foreground hover:bg-accent"
        >
          <span className="truncate">{label}</span>
        </Link>
      ) : (
        <span className="inline-flex max-w-full items-center rounded-full border border-dashed px-2 py-0.5 text-small text-muted-foreground">
          <span className="truncate">{label}</span>
        </span>
      )}
      {actor.dn && (
        <span className="mt-0.5 block truncate font-dn text-caption text-muted-foreground" title={actor.dn}>
          {actor.dn}
        </span>
      )}
    </span>
  )
}

/** The object concerned: label, DN secondary and a link when it still can be opened. */
export function ObjectCell({ event }: { event: AuditEvent }) {
  const { t } = useTranslation()
  const { data: types } = useTypes()
  const { object } = event
  const known = types?.some((x) => x.name === object.type) ?? false
  const found = types?.find((x) => x.name === object.type)
  // plugin and health-check entries have no object type: they are named by audit id.
  const typeLabel = found
    ? translatedTypeLabel(t, found)
    : t(`labels.auditTypes.${object.type}`, { defaultValue: object.type })
  const linkable = known && object.dn.includes('=') && event.action !== 'delete'
  return (
    <span className="block min-w-0">
      <span className="flex items-center gap-1.5">
        {typeLabel && <span className="text-caption text-muted-foreground">{typeLabel}</span>}
        {linkable ? (
          <Link
            to="/types/$type/$dn"
            params={{ type: object.type, dn: object.dn }}
            className="truncate text-body font-medium text-foreground hover:underline"
          >
            {object.label || object.dn}
          </Link>
        ) : (
          <span className="truncate text-body font-medium text-foreground">{object.label || object.dn}</span>
        )}
      </span>
      {object.dn && object.dn !== object.label && (
        <span className="block truncate font-dn text-caption text-muted-foreground" title={object.dn}>
          {object.dn}
        </span>
      )}
    </span>
  )
}

/** Attribute lines of an event as a small before/after list. */
export function AttributeDiff({ lines }: { lines: string[] }) {
  const { t } = useTranslation()
  return (
    <ul className="space-y-1 text-small" aria-label={t('audit.details.title')}>
      {lines.map((line, i) => {
        const c = parseAttribute(line)
        if (c.kind === 'text') {
          return (
            <li key={i} className="font-dn text-muted-foreground">
              {c.text}
            </li>
          )
        }
        const tone =
          c.op === 'delete'
            ? 'text-destructive'
            : c.op === 'add' || c.op === 'set'
              ? 'text-success'
              : 'text-foreground'
        return (
          <li key={i} className="flex flex-wrap items-baseline gap-x-2">
            <span className={cn('w-16 shrink-0 text-caption', tone)}>{t(`audit.details.${c.op}`)}</span>
            <span className="font-dn text-foreground">{c.name}</span>
            <span className="min-w-0 break-all font-dn text-muted-foreground">{c.value}</span>
          </li>
        )
      })}
    </ul>
  )
}

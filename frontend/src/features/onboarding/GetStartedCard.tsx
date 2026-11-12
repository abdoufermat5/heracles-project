import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowRight, CheckCircle2, Circle, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '@/api/endpoints'
import { qk, useMe } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { adminApi } from '@/features/admin/api'
import { ak, useCapabilities } from '@/features/admin/hooks'
import { cn } from '@/lib/utils'

interface Stored {
  dismissed: boolean
  done: string[]
}

const storageKey = (uid: string) => `heracles.getstarted.${uid}`

function load(uid: string): Stored {
  try {
    const raw = localStorage.getItem(storageKey(uid))
    if (raw) {
      const v = JSON.parse(raw) as Partial<Stored>
      return { dismissed: v.dismissed === true, done: Array.isArray(v.done) ? v.done.map(String) : [] }
    }
  } catch {
    /* storage unavailable or corrupt: start fresh */
  }
  return { dismissed: false, done: [] }
}

function save(uid: string, v: Stored): void {
  try {
    localStorage.setItem(storageKey(uid), JSON.stringify(v))
  } catch {
    /* kept in memory for this visit */
  }
}

type ItemId = 'secondFactor' | 'health' | 'access' | 'plugins' | 'import'

interface Item {
  id: ItemId
  to: '/me' | '/admin/health' | '/admin/access' | '/admin/plugins' | '/io'
  /** true: detected from an endpoint; undefined while unknown. Absent for hand-ticked items. */
  auto?: boolean
  detected: boolean
  note?: string
}

/**
 * A dismissible checklist for administrators. Items an endpoint can answer are ticked
 * automatically; the others are ticked by hand. State is kept per user in this browser.
 */
export function GetStartedCard() {
  const { data: me } = useMe()
  const { data: caps } = useCapabilities()
  if (!me || !me.is_admin || caps?.console === false) return null
  return <Checklist uid={me.uid} healthAllowed={caps?.health === true} />
}

function Checklist({ uid, healthAllowed }: { uid: string; healthAllowed: boolean }) {
  const { t } = useTranslation()
  const [stored, setStored] = useState(() => load(uid))
  const totp = useQuery({ queryKey: qk.totp, queryFn: api.totpStatus, retry: false, enabled: !stored.dismissed })
  const checks = useQuery({
    queryKey: ak.checks,
    queryFn: adminApi.checks,
    retry: false,
    enabled: healthAllowed && !stored.dismissed,
  })

  const update = (next: Stored) => {
    setStored(next)
    save(uid, next)
  }
  if (stored.dismissed) return null

  const failing = (checks.data ?? []).filter((c) => c.status !== 'ok').length
  const items: Item[] = [
    {
      id: 'secondFactor',
      to: '/me',
      detected: true,
      auto: totp.data ? totp.data.enabled || totp.data.security_keys > 0 : false,
    },
    {
      id: 'health',
      to: '/admin/health',
      detected: healthAllowed,
      auto: !!checks.data && failing === 0,
      note: failing > 0 ? t('onboarding.items.health.failing', { count: failing }) : undefined,
    },
    { id: 'access', to: '/admin/access', detected: false },
    { id: 'plugins', to: '/admin/plugins', detected: false },
    { id: 'import', to: '/io', detected: false },
  ]
  const isDone = (i: Item) => (i.detected ? i.auto === true : false) || stored.done.includes(i.id)
  const doneCount = items.filter(isDone).length
  const toggle = (id: string) =>
    update({
      ...stored,
      done: stored.done.includes(id) ? stored.done.filter((d) => d !== id) : [...stored.done, id],
    })

  return (
    <section aria-labelledby="getstarted-title" className="rounded-lg border bg-card">
      <div className="flex items-center justify-between gap-3 border-b px-5 py-3.5">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <h2 id="getstarted-title" className="text-body font-semibold text-foreground">
            {t('onboarding.title')}
          </h2>
          <span className="text-small text-muted-foreground">
            {t('onboarding.progress', { done: doneCount, total: items.length })}
          </span>
        </div>
        <Button variant="ghost" size="sm" aria-label={t('onboarding.dismissLabel')} onClick={() => update({ ...stored, dismissed: true })}>
          <X aria-hidden />
          {t('onboarding.dismiss')}
        </Button>
      </div>
      <ul className="divide-y">
        {items.map((item) => {
          const done = isDone(item)
          const title = t(`onboarding.items.${item.id}.title`)
          return (
            <li key={item.id} className="flex items-center gap-3 px-5 py-3">
              {item.detected ? (
                done ? (
                  <CheckCircle2 className="size-5 shrink-0 text-success" aria-label={t('onboarding.done')} />
                ) : (
                  <Circle className="size-5 shrink-0 text-muted-foreground" aria-hidden />
                )
              ) : (
                <input
                  type="checkbox"
                  checked={done}
                  onChange={() => toggle(item.id)}
                  aria-label={t('onboarding.markDone', { item: title })}
                  className="size-4 shrink-0 accent-primary"
                />
              )}
              <div className="min-w-0 flex-1">
                <p className={cn('text-body font-medium', done ? 'text-muted-foreground' : 'text-foreground')}>
                  {title}
                  {item.note && <span className="ml-2 text-small font-normal text-warning">{item.note}</span>}
                </p>
                <p className="text-small text-muted-foreground">{t(`onboarding.items.${item.id}.help`)}</p>
              </div>
              <Button asChild variant="outline" size="sm">
                <Link to={item.to} aria-label={`${t('onboarding.open')}: ${title}`}>
                  {t('onboarding.open')}
                  <ArrowRight aria-hidden />
                </Link>
              </Button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

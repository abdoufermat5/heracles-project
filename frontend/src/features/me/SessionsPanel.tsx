import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Laptop, Loader2, LogOut } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import { qk } from '@/api/hooks'
import type { SessionInfo } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatRelative } from '@/features/audit/format'
import { deviceName } from './device'

const PANEL_HEADER = 'flex h-10 flex-row items-center justify-between border-b px-4 py-0'

const when = (seconds: number) => formatRelative(new Date(seconds * 1000).toISOString())

/** The sessions open on the signed-in person's account, with sign-out of the others. */
export function SessionsPanel() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const sessions = useQuery({ queryKey: qk.sessions, queryFn: api.listSessions })

  const fail = (e: unknown) => toast.error(isApiError(e) ? e.message : t('sessions.failed'))
  const refresh = () => qc.invalidateQueries({ queryKey: qk.sessions })

  const revoke = useMutation({
    mutationFn: (id: string) => api.revokeSession(id),
    onSuccess: refresh,
    onError: fail,
  })
  const revokeOthers = useMutation({
    mutationFn: () => api.revokeOtherSessions(),
    onSuccess: async (r) => {
      toast.success(t('sessions.revoked', { count: r.revoked }))
      await refresh()
    },
    onError: fail,
  })

  const name = (s: SessionInfo) => deviceName(s.user_agent) || t('sessions.unknownDevice')
  const others = (sessions.data ?? []).filter((s) => !s.current)

  return (
    <Card id="portal-sessions" className="gap-0 py-0">
      <CardHeader className={PANEL_HEADER}>
        <CardTitle className="text-lead">{t('sessions.title')}</CardTitle>
        {others.length > 0 && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={revokeOthers.isPending}
            onClick={() => revokeOthers.mutate()}
          >
            {revokeOthers.isPending ? (
              <Loader2 className="animate-spin" aria-hidden="true" />
            ) : (
              <LogOut aria-hidden="true" />
            )}
            {t('sessions.revokeOthers')}
          </Button>
        )}
      </CardHeader>
      <CardContent className="p-0">
        <p className="px-4 pt-3 text-body text-muted-foreground">{t('sessions.help')}</p>
        {sessions.data && sessions.data.length > 0 ? (
          <ul className="mt-3 divide-y border-t text-body" aria-label={t('sessions.title')}>
            {sessions.data.map((s) => (
              <li key={s.id} className="flex items-center gap-3 px-4 py-2.5">
                <Laptop className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-foreground">
                    {name(s)}
                    {s.current && (
                      <span className="ml-2 rounded-sm bg-primary/10 px-1.5 py-0.5 text-caption text-primary">
                        {t('sessions.current')}
                      </span>
                    )}
                  </p>
                  <p className="truncate text-caption text-muted-foreground">
                    {[s.ip, t('sessions.created', { when: when(s.created_at) }), t('sessions.lastSeen', { when: when(s.last_seen) })]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                </div>
                {!s.current && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    disabled={revoke.isPending}
                    onClick={() => revoke.mutate(s.id)}
                    aria-label={t('sessions.revoke', { name: name(s) })}
                    className="text-destructive hover:bg-destructive-soft hover:text-destructive"
                  >
                    <LogOut aria-hidden="true" />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          !sessions.isPending && (
            <p className="px-4 py-3 text-body text-muted-foreground">{t('sessions.none')}</p>
          )
        )}
      </CardContent>
    </Card>
  )
}

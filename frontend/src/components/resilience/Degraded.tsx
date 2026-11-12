import { WifiOff } from 'lucide-react'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { subscribeApiEvents } from '@/api/client'
import { api } from '@/api/endpoints'
import { useMe } from '@/api/hooks'
import type { ServerStatus } from '@/api/types'
import { APP_VERSION } from '@/lib/appVersion'

const POLL_MS = 30_000

interface Degraded {
  offline: boolean
  /** Directory of the signed-in user cannot be reached at all. */
  down: boolean
  /** Only read replicas answer. */
  readOnly: boolean
}

const HEALTHY: Degraded = { offline: false, down: false, readOnly: false }
const DegradedContext = createContext<Degraded>(HEALTHY)

/** False while the directory is unreachable or read-only, or the browser is offline. */
export function useWritesAllowed(): boolean {
  const d = useContext(DegradedContext)
  return !(d.offline || d.down || d.readOnly)
}

function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine)
  useEffect(() => {
    const on = () => setOnline(true)
    const off = () => setOnline(false)
    window.addEventListener('online', on)
    window.addEventListener('offline', off)
    return () => {
      window.removeEventListener('online', on)
      window.removeEventListener('offline', off)
    }
  }, [])
  return online
}

/** Polls `/status`, tracks degraded mode and announces a new server build. */
export function DegradedProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const online = useOnline()
  const me = useMe().data
  const [status, setStatus] = useState<ServerStatus | null>(null)

  const refresh = useCallback(() => {
    api.status().then(setStatus, () => undefined) // 401 (signed out) or unreachable: keep the last state
  }, [])

  const signedIn = Boolean(me)
  useEffect(() => {
    if (!signedIn) return // /status needs a session; nothing to poll on the sign-in pages
    refresh()
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') refresh()
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [refresh, signedIn])

  useEffect(() => {
    let announced = false
    return subscribeApiEvents({
      onDirectoryUnavailable: refresh,
      onServerVersion: (version) => {
        if (announced || version === APP_VERSION) return
        announced = true
        toast(t('resilience.newVersion'), {
          id: 'new-version',
          duration: Infinity,
          action: { label: t('resilience.reload'), onClick: () => window.location.reload() },
        })
      },
    })
  }, [refresh, t])

  const value = useMemo<Degraded>(() => {
    const dirs = status?.directories ?? {}
    const mine = me ? dirs[me.directory] : undefined
    const all = mine ? [mine] : Object.values(dirs)
    return {
      offline: !online,
      down: all.some((d) => !d.available),
      readOnly: all.some((d) => d.available && d.read_only),
    }
  }, [status, me, online])

  return (
    <DegradedContext.Provider value={value}>
      {children}
      <DegradedBanner state={value} />
    </DegradedContext.Provider>
  )
}

function DegradedBanner({ state }: { state: Degraded }) {
  const { t } = useTranslation()
  const message = state.offline
    ? t('resilience.offline')
    : state.down
      ? t('resilience.degradedDown')
      : state.readOnly
        ? t('resilience.degradedReadOnly')
        : null
  if (!message) return null
  return (
    <div
      role="status"
      className="fixed left-1/2 top-2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-body shadow-overlay"
    >
      <WifiOff className="size-4 text-destructive" aria-hidden />
      {message}
    </div>
  )
}

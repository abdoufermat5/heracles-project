import { useCallback, useEffect, useState } from 'react'
import { solveChallenge } from '@/features/auth/pow'
import { publicApi } from './api'

export interface CaptchaState {
  /** Token and counter to send once the check is solved and the minimum fill time is over. */
  answer: { token: string; counter: string } | null
  /** The browser is still working on it and it has taken more than a second. */
  slow: boolean
  /** Ask for a fresh challenge (after a failed submission; each one is single use). */
  renew: () => void
}

/** Seconds until the challenge expires, from the signed payload (a fallback if unreadable). */
function lifetime(token: string): number {
  try {
    const body = (token.split('.')[0] ?? '').replace(/-/g, '+').replace(/_/g, '/')
    const data = JSON.parse(atob(body)) as { i?: number; e?: number }
    if (typeof data.i === 'number' && typeof data.e === 'number') return data.e - data.i
  } catch {
    /* not readable: use the default */
  }
  return 540
}

/**
 * Solve the form's proof-of-work in the background as soon as it is enabled, and again
 * whenever the challenge expires or `renew` is called. `answer` is set only once the server's
 * minimum fill time has passed since the challenge was issued.
 */
export function useCaptcha(name: string, enabled: boolean): CaptchaState {
  const [answer, setAnswer] = useState<CaptchaState['answer']>(null)
  const [slow, setSlow] = useState(false)
  const [round, setRound] = useState(0)

  useEffect(() => {
    if (!enabled) return
    let live = true
    const timers: number[] = []
    const later = (fn: () => void, ms: number) => {
      timers.push(window.setTimeout(fn, ms))
    }
    later(() => setSlow(true), 1000)
    void (async () => {
      try {
        const started = Date.now()
        const challenge = await publicApi.captcha(name)
        const counter = await solveChallenge(challenge)
        if (!live) return
        const wait = Math.max(0, challenge.min_fill_seconds * 1000 - (Date.now() - started))
        later(() => {
          setSlow(false)
          setAnswer({ token: challenge.token, counter })
        }, wait)
        later(() => {
          setAnswer(null)
          setRound((r) => r + 1)
        }, lifetime(challenge.token) * 1000 - 5000)
      } catch {
        // Could not fetch or solve: try again shortly instead of leaving the form stuck.
        if (live) later(() => setRound((r) => r + 1), 5000)
      }
    })()
    return () => {
      live = false
      timers.forEach((t) => window.clearTimeout(t))
      setSlow(false)
    }
  }, [name, enabled, round])

  const renew = useCallback(() => {
    setAnswer(null)
    setRound((r) => r + 1)
  }, [])
  return { answer, slow, renew }
}

import { createContext, useContext, useMemo, useState } from 'react'

export type Scope = 'one' | 'sub'

interface ScopeValue {
  /** Selected department DN (null = the user's base). */
  base: string | null
  scope: Scope
  setBase: (dn: string | null) => void
  setScope: (s: Scope) => void
}

const ScopeContext = createContext<ScopeValue | null>(null)
const KEY = 'heracles.scope'

function load(): { base: string | null; scope: Scope } {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const j = JSON.parse(raw) as { base?: string | null; scope?: Scope }
      return { base: j.base ?? null, scope: j.scope === 'one' ? 'one' : 'sub' }
    }
  } catch {
    /* ignore */
  }
  return { base: null, scope: 'sub' }
}

export function ScopeProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState(load)
  const value = useMemo<ScopeValue>(() => {
    const persist = (s: { base: string | null; scope: Scope }) => {
      try {
        localStorage.setItem(KEY, JSON.stringify(s))
      } catch {
        /* ignore */
      }
    }
    return {
      ...state,
      setBase: (base) =>
        setState((s) => {
          const n = { ...s, base }
          persist(n)
          return n
        }),
      setScope: (scope) =>
        setState((s) => {
          const n = { ...s, scope }
          persist(n)
          return n
        }),
    }
  }, [state])
  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useScope(): ScopeValue {
  const ctx = useContext(ScopeContext)
  if (!ctx) throw new Error('useScope must be used within ScopeProvider')
  return ctx
}

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { render } from '@testing-library/react'
import { App } from '@/App'
import { db } from '@/mocks/db'

export function signIn(user = 'admin'): void {
  db.session = { user, pending: null }
}

export function newClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
}

/** Render the whole app at a given URL. */
export function renderApp(path: string) {
  const history = createMemoryHistory({ initialEntries: [path] })
  const client = newClient()
  return { history, client, ...render(<App history={history} client={client} />) }
}

/** Render a component that needs React Query only. */
export function renderWithQuery(ui: React.ReactElement) {
  const client = newClient()
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

export function userDn(index = 0): string {
  const rec = db.all('user')[index]
  if (!rec) throw new Error('no user')
  return rec.dn
}

export const userPath = (index = 0): string => `/types/user/${encodeURIComponent(userDn(index))}`

export function must<T>(v: T | undefined | null): T {
  if (v === undefined || v === null) throw new Error('expected a value')
  return v
}

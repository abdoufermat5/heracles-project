import type { QueryClient } from '@tanstack/react-query'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, type RouterHistory } from '@tanstack/react-router'
import { useMemo } from 'react'
import { setSetupRequiredHandler, setUnauthenticatedHandler } from '@/api/client'
import { createQueryClient } from '@/queryClient'
import { Toaster } from '@/components/ui/sonner'
import { ScopeProvider } from '@/lib/scope'
import { ThemeProvider } from '@/lib/theme'
import { createAppRouter } from '@/router'

export function App({ history, client }: { history?: RouterHistory; client?: QueryClient }) {
  const queryClient = useMemo(() => client ?? createQueryClient(), [client])
  const router = useMemo(() => {
    const r = createAppRouter(queryClient, history)
    setUnauthenticatedHandler(() => {
      queryClient.clear()
      void r.navigate({ to: '/login', search: { redirect: undefined } })
    })
    setSetupRequiredHandler(() => {
      if (r.state.location.pathname !== '/setup') void r.navigate({ to: '/setup' })
    })
    return r
  }, [queryClient, history])

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ScopeProvider>
          <RouterProvider router={router} />
          <Toaster position="bottom-right" />
        </ScopeProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

import type { QueryClient } from '@tanstack/react-query'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, type RouterHistory } from '@tanstack/react-router'
import { useMemo } from 'react'
import { setUnauthenticatedHandler } from '@/api/client'
import { createQueryClient } from '@/queryClient'
import { DegradedProvider, SessionExpiry } from '@/components/resilience'
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
    return r
  }, [queryClient, history])

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ScopeProvider>
          <DegradedProvider>
            <RouterProvider router={router} />
          </DegradedProvider>
          <SessionExpiry />
          <Toaster position="bottom-right" />
        </ScopeProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

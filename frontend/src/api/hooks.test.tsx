import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import '@/i18n'
import { server } from '@/mocks/server'
import type { ObjectList } from './types'
import { qk, useAccountLock } from './hooks'

const DN = 'uid=a,dc=x'
const listKey = qk.list('user', {})
const list = (locked: boolean): ObjectList => ({
  items: [{ dn: DN, values: {}, locked }],
  next_cursor: null,
  total: 1,
})

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  qc.setQueryData(listKey, list(false))
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  return { qc, ...renderHook(() => useAccountLock('user'), { wrapper }) }
}

describe('useAccountLock', () => {
  it('shows the lock at once', async () => {
    server.use(http.post('/api/v2/users/:dn/lock', async () => {
      await new Promise((r) => setTimeout(r, 50))
      return new HttpResponse(null, { status: 204 })
    }))
    const { qc, result } = setup()
    act(() => result.current.mutate({ dns: [DN], lock: true }))
    await waitFor(() => expect(qc.getQueryData<ObjectList>(listKey)?.items[0]?.locked).toBe(true))
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })

  it('puts the list back when the request fails', async () => {
    server.use(http.post('/api/v2/users/:dn/lock', () => HttpResponse.error()))
    const { qc, result } = setup()
    act(() => result.current.mutate({ dns: [DN], lock: true }))
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.failed).toBe(1)
    await waitFor(() => expect(qc.getQueryData<ObjectList>(listKey)?.items[0]?.locked).toBe(false))
  })
})

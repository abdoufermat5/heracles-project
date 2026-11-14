import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { ApiError, request } from '@/api/client'
import { qk } from '@/api/hooks'
import { db } from '@/mocks/db'
import { server } from '@/mocks/server'
import { signIn } from '@/test/utils'
import { ErrorPanel, SessionExpiry } from '.'

describe('ErrorPanel', () => {
  it('shows the request id of the failed response in the details', () => {
    const err = new ApiError(502, { code: 'ldap_error', message: 'Directory said no' }, 'req-1234')
    render(<ErrorPanel error={err} onRetry={() => undefined} />)
    expect(screen.getByTestId('request-id')).toHaveTextContent('req-1234')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy details' })).toBeInTheDocument()
  })
})

describe('session expiry', () => {
  it('asks to sign in again, then retries the failed request', async () => {
    signIn('admin')
    const qc = new QueryClient()
    qc.setQueryData(qk.me, db.me())
    render(
      <QueryClientProvider client={qc}>
        <SessionExpiry />
      </QueryClientProvider>,
    )
    // the session expires under a call
    db.session = { user: null, pending: null }
    let served = 0
    server.use(
      http.get('/api/v2/ping', () => {
        served += 1
        return db.me()
          ? HttpResponse.json({ ok: true })
          : HttpResponse.json({ error: { code: 'unauthenticated', message: 'no' } }, { status: 401 })
      }),
    )
    const result = request<{ ok: boolean }>('/ping')
    await userEvent.type(await screen.findByLabelText('Password'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await expect(result).resolves.toEqual({ ok: true })
    expect(served).toBe(2)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})

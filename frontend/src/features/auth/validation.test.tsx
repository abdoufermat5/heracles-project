import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/mocks/server'
import { renderApp } from '@/test/utils'

describe('sign-in form', () => {
  it('asks for both values inline and does not send an empty form', async () => {
    let sent = 0
    server.use(
      http.post('/api/v2/auth/login', () => {
        sent++
        return HttpResponse.json({ status: 'ok' })
      }),
    )
    const user = userEvent.setup()
    renderApp('/login')
    await user.click(await screen.findByRole('button', { name: 'Sign in' }))
    const alerts = await screen.findAllByRole('alert')
    expect(alerts.map((a) => a.textContent)).toEqual(['This field is required', 'This field is required'])
    expect(screen.getByLabelText('Username')).toHaveAttribute('aria-invalid', 'true')
    expect(sent).toBe(0)
  })
})

describe('password recovery request', () => {
  it('refuses a malformed address before sending it', async () => {
    let sent = 0
    server.use(
      http.post('/api/v2/auth/recovery', () => {
        sent++
        return new HttpResponse(null, { status: 202 })
      }),
    )
    const user = userEvent.setup()
    renderApp('/recovery')
    const email = await screen.findByLabelText(/Email/)
    await user.type(email, 'not-an-address')
    await user.tab()
    expect(await screen.findByText('Enter a valid email address')).toHaveAttribute('role', 'alert')
    expect(email).toHaveAttribute('aria-invalid', 'true')
    await user.click(screen.getByRole('button', { name: /Send/ }))
    expect(sent).toBe(0)
    expect(email).toHaveValue('not-an-address')
  })
})

describe('password reset', () => {
  const link = '/recovery/confirm?login=jdoe&token=t0ken'

  it('uses the live policy length and a matching confirmation', async () => {
    server.use(http.get('/api/v2/auth/password-policy', () => HttpResponse.json({ min_length: 10 })))
    let sent = 0
    server.use(
      http.post('/api/v2/auth/recovery/confirm', () => {
        sent++
        return HttpResponse.json({ status: 'ok' })
      }),
    )
    const user = userEvent.setup()
    renderApp(link)
    expect(await screen.findByText('Use at least 10 characters.')).toBeInTheDocument()
    const password = screen.getByLabelText('New password')
    await user.type(password, 'ninechars')
    await user.tab()
    expect(await screen.findByText('Must be at least 10 characters')).toHaveAttribute('role', 'alert')
    await user.type(screen.getByLabelText('Confirm password'), 'different')
    await user.click(screen.getByRole('button', { name: /Reset|Change|Set/ }))
    await waitFor(() => expect(screen.getByLabelText('Confirm password')).toHaveAttribute('aria-invalid', 'true'))
    expect(sent).toBe(0)
  })

  it('shows the server policy verdict under the password field', async () => {
    server.use(
      http.post('/api/v2/auth/recovery/confirm', () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation',
              message: 'Password rejected',
              fields: { password: 'This password is too common.' },
            },
          },
          { status: 422 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderApp(link)
    await user.type(await screen.findByLabelText('New password'), 'long enough password')
    await user.type(screen.getByLabelText('Confirm password'), 'long enough password')
    await user.click(screen.getByRole('button', { name: /Reset|Change|Set/ }))
    expect(await screen.findByText('This password is too common.')).toHaveAttribute('role', 'alert')
    expect(screen.getByLabelText('New password')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('New password')).toHaveValue('long enough password')
  })
})

describe('second factor', () => {
  it('asks for the 6 digits inline', async () => {
    const user = userEvent.setup()
    renderApp('/login/second-factor?methods=totp')
    await user.click(await screen.findByRole('button', { name: /Verify/ }))
    expect(await screen.findByText('This field is required')).toHaveAttribute('role', 'alert')
    await user.type(screen.getByRole('group').querySelector('input') as HTMLInputElement, '123')
    await user.click(screen.getByRole('button', { name: /Verify/ }))
    await waitFor(() =>
      expect(screen.getAllByRole('alert').map((a) => a.textContent)).toContain(
        'Enter the 6-digit code from your authenticator app.',
      ),
    )
  })
})

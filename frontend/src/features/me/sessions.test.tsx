import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { db } from '@/mocks/db'
import { renderApp, signIn } from '@/test/utils'
import { deviceName } from './device'

describe('sessions panel', () => {
  it('names a device from its user agent', () => {
    expect(deviceName('Mozilla/5.0 (X11; Linux x86_64; rv:1) Gecko/20100101 Firefox/130.0')).toBe(
      'Firefox on Linux',
    )
    expect(deviceName('')).toBe('')
  })

  it('lists the sessions, marks the current one and signs another out', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/me')

    expect(await screen.findByText('Safari on iOS')).toBeInTheDocument()
    expect(screen.getByText('This device')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign out Firefox on Linux' })).toBeNull()

    await user.click(screen.getByRole('button', { name: 'Sign out Safari on iOS' }))
    await waitFor(() => expect(screen.queryByText('Safari on iOS')).not.toBeInTheDocument())
    expect(db.sessions.map((s) => s.id)).toEqual(['cur'])
  })

  it('signs out every other device at once', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'Sign out all other devices' }))
    await waitFor(() => expect(db.sessions).toHaveLength(1))
    expect(await screen.findByText('1 device signed out.')).toBeInTheDocument()
  })
})

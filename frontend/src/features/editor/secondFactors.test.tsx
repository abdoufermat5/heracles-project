import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { db } from '@/mocks/db'
import { server } from '@/mocks/server'
import { renderApp, signIn, userDn, userPath } from '@/test/utils'
import { objectsApi } from './api'

const FULL = {
  totp: true,
  security_keys: [
    { id: 'key-desk', label: 'Desk key' },
    { id: 'key-phone', label: '' },
  ],
  recovery_codes: 6,
}

async function openEditor(index = 0) {
  renderApp(userPath(index))
  await screen.findByRole('heading', { level: 1 })
}

describe('second factors panel', () => {
  it('shows what the user registered and nothing secret', async () => {
    signIn()
    db.secondFactors.set(userDn(0).toLowerCase(), structuredClone(FULL))
    await openEditor()
    await userEvent.click(await screen.findByRole('tab', { name: /Security|Second factors/ }))

    expect(await screen.findByText('Enabled')).toBeInTheDocument()
    const keys = within(screen.getByRole('list', { name: 'Security keys' }))
    expect(keys.getByText('Desk key')).toBeInTheDocument()
    expect(keys.getByText('Unnamed key')).toBeInTheDocument()
    expect(screen.getByText('6 unused codes')).toBeInTheDocument()
  })

  it('resets every second factor after a confirmation', async () => {
    signIn()
    db.secondFactors.set(userDn(0).toLowerCase(), structuredClone(FULL))
    await openEditor()
    await userEvent.click(await screen.findByRole('tab', { name: /Security|Second factors/ }))
    await screen.findByText('Enabled')

    await userEvent.click(screen.getByRole('button', { name: 'Reset second factors' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Reset all second factors?')
    // cancelling changes nothing
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(db.secondFactors.get(userDn(0).toLowerCase())?.totp).toBe(true)

    await userEvent.click(screen.getByRole('button', { name: 'Reset second factors' }))
    await userEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Reset' }),
    )
    expect(await screen.findByText('Not set up')).toBeInTheDocument()
    expect(screen.getByText('No security keys.')).toBeInTheDocument()
    expect(db.secondFactors.has(userDn(0).toLowerCase())).toBe(false)
    expect(screen.getByRole('button', { name: 'Reset second factors' })).toBeDisabled()
  })

  it('removes a single security key after a confirmation', async () => {
    signIn()
    db.secondFactors.set(userDn(0).toLowerCase(), structuredClone(FULL))
    await openEditor()
    await userEvent.click(await screen.findByRole('tab', { name: /Security|Second factors/ }))
    await screen.findByText('Desk key')

    await userEvent.click(screen.getByRole('button', { name: 'Remove Desk key' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Remove this security key?')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(screen.queryByText('Desk key')).not.toBeInTheDocument())
    expect(screen.getByText('Unnamed key')).toBeInTheDocument()
    expect(db.secondFactors.get(userDn(0).toLowerCase())).toMatchObject({
      totp: true,
      recovery_codes: 6,
    })
  })

  it('disables the reset for a user without second factors', async () => {
    signIn()
    await openEditor()
    await userEvent.click(await screen.findByRole('tab', { name: /Security|Second factors/ }))
    expect(await screen.findByText('Not set up')).toBeInTheDocument()
    expect(screen.getByText(/signing in needs only the password/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reset second factors' })).toBeDisabled()
  })

  it('is view only without the right to reset', async () => {
    signIn()
    server.use(
      http.get('/api/v2/users/:dn/second-factors', () =>
        HttpResponse.json({ ...FULL, can_reset: false }),
      ),
    )
    await openEditor()
    await userEvent.click(await screen.findByRole('tab', { name: /Security|Second factors/ }))
    await screen.findByText('Desk key')
    expect(screen.getByText(/view these second factors but not remove them/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reset second factors' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Remove Desk key' })).not.toBeInTheDocument()
  })

  it('is not offered to users who may not see second factors', async () => {
    signIn('viewer')
    const spy = vi.spyOn(objectsApi, 'secondFactors')
    await openEditor()
    await waitFor(() => expect(spy).toHaveBeenCalled())
    await expect(spy.mock.results[0]?.value).rejects.toMatchObject({ status: 403 })
    await userEvent.click(await screen.findByRole('tab', { name: /Security|Second factors/ }))
    expect(await screen.findByText(/cannot view the second factors/i)).toBeInTheDocument()
  })

  it('is not offered when creating a user', async () => {
    signIn()
    renderApp('/types/user/new')
    await screen.findByRole('heading', { level: 1 })
    expect(screen.queryByRole('tab', { name: 'Second factors' })).not.toBeInTheDocument()
  })
})

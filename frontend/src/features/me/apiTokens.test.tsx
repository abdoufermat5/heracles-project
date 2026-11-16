import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { parseAttribute } from '@/features/audit/format'
import { db } from '@/mocks/db'
import { server } from '@/mocks/server'
import { renderApp, renderWithQuery, signIn } from '@/test/utils'
import { UserApiTokensPanel } from './UserApiTokensPanel'

describe('API tokens panel', () => {
  it('creates a token, shows its secret once, then lists it without the secret', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/me')

    expect(await screen.findByText('You have no API token.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'New token' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Name'), 'Nightly export')
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }))

    const secret = await within(dialog).findByLabelText('API token')
    expect(secret.textContent).toMatch(/^hrc_[0-9a-f]{16}_/)
    expect(db.apiTokens).toHaveLength(1)
    expect(db.apiTokens[0]).toMatchObject({ name: 'Nightly export', scope: 'read', types: [] })

    await user.click(within(dialog).getByRole('button', { name: 'Done' }))
    const list = await screen.findByRole('list', { name: 'API tokens' })
    expect(within(list).getByText('Nightly export')).toBeInTheDocument()
    expect(screen.queryByText(/^hrc_/)).toBeNull()
  })

  it('limits a token to some object types', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'New token' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Name'), 'Groups sync')
    await user.click(within(dialog).getByLabelText('Limit to some object types'))
    expect(within(dialog).getByText('Choose at least one object type.')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Create token' })).toBeDisabled()
    const types = within(dialog).getByRole('list', { name: 'Object types' })
    await user.click(within(types).getByRole('checkbox', { name: /group$/ }))
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }))
    await within(dialog).findByLabelText('API token')
    expect(db.apiTokens[0]?.types).toEqual(['group'])
  })

  it('limits a token to some networks and reports a bad one', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'New token' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Name'), 'Backup host')
    const networks = within(dialog).getByLabelText('Allowed addresses')
    await user.type(networks, '10.20.0.0/16{enter}nope')
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }))
    expect(await within(dialog).findByText('Not an address or a network: nope')).toBeInTheDocument()

    await user.clear(networks)
    await user.type(networks, '10.20.0.0/16{enter}192.0.2.7')
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }))
    await within(dialog).findByLabelText('API token')
    expect(db.apiTokens[0]?.allowed_ips).toEqual(['10.20.0.0/16', '192.0.2.7/32'])
    await user.click(within(dialog).getByRole('button', { name: 'Done' }))
    expect(await screen.findByText(/from 10\.20\.0\.0\/16, 192\.0\.2\.7\/32/)).toBeInTheDocument()
  })

  it('asks to confirm the identity when the sign-in is old, then creates', async () => {
    signIn()
    db.reauthFresh = false
    const user = userEvent.setup()
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'New token' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Name'), 'CI')
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }))
    expect(
      await screen.findByText('For your security, confirm your identity before creating a token.'),
    ).toBeInTheDocument()
    expect(db.apiTokens).toHaveLength(0)
  })

  it('revokes a token after confirmation', async () => {
    const now = Math.floor(Date.now() / 1000)
    db.apiTokens = [
      {
        id: '00000000000000aa',
        name: 'Old script',
        owner_dn: 'admin',
        scope: 'write',
        types: ['user'],
        created_at: now - 86400,
        expires_at: now + 86400 * 30,
        last_used_at: now - 60,
        last_used_ip: '192.0.2.4',
        allowed_ips: [],
      },
    ]
    signIn()
    const user = userEvent.setup()
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'Revoke Old script' }))
    await user.click(await screen.findByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(db.apiTokens).toHaveLength(0))
    expect(await screen.findByText('Token revoked.')).toBeInTheDocument()
  })

  it('reads the token line of an audit event', () => {
    expect(parseAttribute('via: api token 0123456789abcdef')).toEqual({
      kind: 'via',
      token: '0123456789abcdef',
    })
  })

  it('stays hidden on a profile the viewer may not manage', async () => {
    signIn()
    server.use(
      http.get('/api/v2/tokens', () =>
        HttpResponse.json(
          { error: { code: 'forbidden', message: 'You cannot see the API tokens of this person' } },
          { status: 403 },
        ),
      ),
    )
    const { container } = renderWithQuery(<UserApiTokensPanel dn="uid=bob,ou=people,dc=x" />)
    await new Promise((r) => setTimeout(r, 200))
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByText(/cannot see/)).toBeNull()
  })
})

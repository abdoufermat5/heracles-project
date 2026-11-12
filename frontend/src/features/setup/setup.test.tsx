import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { resetSetupMock, setupMock } from '@/mocks/setupHandlers'
import { server } from '@/mocks/server'
import { renderApp } from '@/test/utils'

afterEach(() => {
  resetSetupMock()
  sessionStorage.clear()
})

async function verifyToken(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText('Setup token'), setupMock.token)
  await user.click(screen.getByRole('button', { name: 'Verify token' }))
  await screen.findByRole('heading', { name: 'Directory' })
}

async function fillDirectory(user: ReturnType<typeof userEvent.setup>, password: string) {
  const uri = screen.getByLabelText('Server URI')
  await user.clear(uri)
  await user.type(uri, 'ldap://ldap.example.org')
  await user.type(screen.getByLabelText('Bind DN'), 'cn=admin,dc=example,dc=org')
  await user.type(screen.getByLabelText('Bind password'), password)
  await user.click(screen.getByRole('button', { name: 'Test connection' }))
}

describe('first-run setup', () => {
  it('sends the user to /setup when the server asks for it', async () => {
    setupMock.required = true
    server.use(
      http.get('/api/v2/auth/me', () =>
        HttpResponse.json({ error: { code: 'setup_required', message: 'Setup required' } }, { status: 503 }),
      ),
    )
    const { history } = renderApp('/')
    await screen.findByRole('heading', { name: 'Welcome' })
    expect(history.location.pathname).toBe('/setup')
  })

  it('rejects a wrong setup token', async () => {
    setupMock.required = true
    const user = userEvent.setup()
    renderApp('/setup')
    await user.type(await screen.findByLabelText('Setup token'), 'nope')
    await user.click(screen.getByRole('button', { name: 'Verify token' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('not valid')
    expect(screen.queryByRole('heading', { name: 'Directory' })).not.toBeInTheDocument()
  })

  it('shows what failed when the connection test fails, and blocks continuing', async () => {
    setupMock.required = true
    const user = userEvent.setup()
    renderApp('/setup')
    await verifyToken(user)
    await fillDirectory(user, 'wrong')
    const result = await screen.findByRole('region', { name: 'Connection test' })
    expect(within(result).getByText('Invalid credentials for the bind DN.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
  })

  it('walks through every step and applies the configuration', async () => {
    setupMock.required = true
    const user = userEvent.setup()
    renderApp('/setup')
    await verifyToken(user)

    await fillDirectory(user, 'secret')
    // the base DN is adopted from the server's naming contexts, then checked
    await waitFor(() => expect(screen.getByLabelText('Base DN')).toHaveValue('dc=example,dc=org'))
    const result = await screen.findByRole('region', { name: 'Connection test' })
    expect(within(result).getByText('Writable')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    // schema already installed
    await screen.findByText('The Heracles schema is installed in this directory.')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await user.type(await screen.findByLabelText('First name'), 'Ada')
    await user.type(screen.getByLabelText('Last name'), 'Lovelace')
    await user.type(screen.getByLabelText('Email'), 'ada@example.org')
    await user.type(screen.getByLabelText('Password'), 'correct horse battery')
    await user.type(await screen.findByLabelText('Confirm password'), 'correct horse battery')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    // the default profile is preselected
    await screen.findByText('Audit log')
    expect(screen.getByRole('radio', { name: /Core/ })).toBeChecked()
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await screen.findByRole('heading', { name: 'Review' })
    expect(screen.getByText('cn=admin,dc=example,dc=org')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Apply and finish' }))

    await screen.findByRole('heading', { name: 'Heracles is ready' })
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
    expect(setupMock.applied).toMatchObject({
      admin: { uid: 'admin', given_name: 'Ada' },
      plugins: ['posix', 'audit'],
      public_url: null,
    })
  })

  it('offers the schema download when classes are missing', async () => {
    setupMock.required = true
    setupMock.schemaInstalled = false
    const user = userEvent.setup()
    renderApp('/setup')
    await verifyToken(user)
    await fillDirectory(user, 'secret')
    await waitFor(() => expect(screen.getByLabelText('Base DN')).toHaveValue('dc=example,dc=org'))
    await user.click(await screen.findByRole('button', { name: 'Continue' }))
    await screen.findByText('hrcPerson')
    expect(screen.getByText('ldapadd -Y EXTERNAL -H ldapi:/// -f heracles.ldif')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
    setupMock.schemaInstalled = true
    await user.click(screen.getByRole('button', { name: 'Check again' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled())
  })
})

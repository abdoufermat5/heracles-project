import { screen, waitFor } from '@testing-library/react'
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

async function toDirectory(user: ReturnType<typeof userEvent.setup>) {
  setupMock.required = true
  renderApp('/setup')
  await user.type(await screen.findByLabelText('Setup token'), setupMock.token)
  await user.click(screen.getByRole('button', { name: 'Verify token' }))
  await screen.findByRole('heading', { name: 'Directory' })
}

async function passDirectory(user: ReturnType<typeof userEvent.setup>) {
  const uri = screen.getByLabelText('Server URI')
  await user.clear(uri)
  await user.type(uri, 'ldap://ldap.example.org')
  await user.type(screen.getByLabelText('Bind DN'), 'cn=admin,dc=example,dc=org')
  await user.type(screen.getByLabelText('Bind password'), 'secret')
  await user.click(screen.getByRole('button', { name: 'Test connection' }))
  await waitFor(() => expect(screen.getByLabelText('Base DN')).toHaveValue('dc=example,dc=org'))
  await user.click(await screen.findByRole('button', { name: 'Continue' }))
  await user.click(await screen.findByRole('button', { name: 'Continue' }))
}

describe('setup wizard validation', () => {
  it('refuses a malformed address, DN and CA path before testing the connection', async () => {
    const user = userEvent.setup()
    await toDirectory(user)
    const uri = screen.getByLabelText('Server URI')
    await user.clear(uri)
    await user.type(uri, 'http://ldap.example.org')
    await user.type(screen.getByLabelText('Bind DN'), 'admin')
    await user.type(screen.getByLabelText('Bind password'), 'secret')
    await user.type(screen.getByLabelText('CA certificate file'), 'ca.pem')
    await user.type(screen.getByLabelText('Base DN'), 'example.org')
    await user.tab()

    expect(await screen.findByText(/Use an address such as ldap:\/\//)).toHaveAttribute('role', 'alert')
    expect(screen.getByText(/Enter a distinguished name/, { selector: '#dir-bind_dn-error' })).toBeInTheDocument()
    expect(screen.getByText(/Enter an absolute path/)).toBeInTheDocument()
    expect(uri).toHaveAttribute('aria-invalid', 'true')
    expect(uri).toHaveValue('http://ldap.example.org')
    expect(screen.getByText('Fix 4 invalid fields to continue.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Test connection' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
  })

  it('shows what the server refused under the same field and drops it when edited', async () => {
    const user = userEvent.setup()
    await toDirectory(user)
    server.use(
      http.post('/api/v2/setup/directory/test', () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation',
              message: 'Some fields are not valid',
              fields: { base_dn: 'The server refused this base DN.' },
            },
          },
          { status: 422 },
        ),
      ),
    )
    const uri = screen.getByLabelText('Server URI')
    await user.clear(uri)
    await user.type(uri, 'ldap://ldap.example.org')
    await user.type(screen.getByLabelText('Bind DN'), 'cn=admin,dc=example,dc=org')
    await user.type(screen.getByLabelText('Bind password'), 'secret')
    await user.type(screen.getByLabelText('Base DN'), 'dc=example,dc=org')
    await user.click(screen.getByRole('button', { name: 'Test connection' }))

    const message = await screen.findByText('The server refused this base DN.')
    expect(message).toHaveAttribute('role', 'alert')
    expect(screen.getByLabelText('Base DN')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Base DN')).toHaveValue('dc=example,dc=org')

    await user.type(screen.getByLabelText('Base DN'), ',dc=x')
    await waitFor(() =>
      expect(screen.queryByText('The server refused this base DN.')).not.toBeInTheDocument(),
    )
  })

  it('checks the administrator form and the password length before moving on', async () => {
    const user = userEvent.setup()
    await toDirectory(user)
    await passDirectory(user)
    await screen.findByRole('heading', { name: 'Administrator' })

    const login = screen.getByLabelText('Login')
    await user.clear(login)
    await user.type(login, 'a b')
    await user.type(screen.getByLabelText('First name'), 'Ada')
    await user.type(screen.getByLabelText('Email'), 'not-an-address')
    await user.type(screen.getByLabelText('Password'), 'short')
    await user.tab()
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByText(/Use up to 64 letters/)).toBeInTheDocument()
    expect(screen.getByText('Enter a valid email address')).toBeInTheDocument()
    expect(screen.getByText('Must be at least 8 characters')).toBeInTheDocument()
    expect(screen.getByLabelText('Last name')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: 'Continue' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('heading', { name: 'Administrator' })).toBeInTheDocument()
    expect(login).toHaveValue('a b')
  })

  it('asks for a matching confirmation', async () => {
    const user = userEvent.setup()
    await toDirectory(user)
    await passDirectory(user)
    await user.type(await screen.findByLabelText('First name'), 'Ada')
    await user.type(screen.getByLabelText('Last name'), 'Lovelace')
    await user.type(screen.getByLabelText('Email'), 'ada@example.org')
    await user.type(screen.getByLabelText('Password'), 'correct horse battery')
    await user.type(await screen.findByLabelText('Confirm password'), 'correct horse')
    expect(await screen.findByText('Passwords do not match')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue' })).toHaveAttribute('aria-disabled', 'true')
  })
})

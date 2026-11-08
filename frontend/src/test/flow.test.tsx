import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { db } from '@/mocks/db'
import { renderApp } from '@/test/utils'

describe('full flow', () => {
  it('login -> list users -> edit -> save', async () => {
    const { history } = renderApp('/types/user')

    // unauthenticated: redirected to the login page
    expect(await screen.findByRole('heading', { name: 'Sign in to Heracles' })).toBeInTheDocument()
    expect(history.location.pathname).toBe('/login')

    await userEvent.type(screen.getByLabelText('Username'), 'admin')
    await userEvent.type(screen.getByLabelText('Password'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    // back on the originally requested page
    expect(await screen.findByText('200 items')).toBeInTheDocument()
    expect(history.location.pathname).toBe('/types/user')

    // open the first user
    const first = db.all('user').sort((a, b) =>
      String(a.tabs.main?.values.uid).localeCompare(String(b.tabs.main?.values.uid), undefined, { numeric: true }),
    )[0]
    if (!first) throw new Error('no users')
    await userEvent.click(await screen.findByRole('link', { name: String(first.tabs.main?.values.uid) }))
    const given = await screen.findByLabelText(/^First name/ )
    expect(given).toBeDisabled()

    // edit and save
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    await waitFor(() => expect(given).toBeEnabled())
    await userEvent.clear(given)
    await userEvent.type(given, 'Zed')
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))

    await waitFor(() => expect(screen.getByLabelText(/^First name/ )).toBeDisabled())
    expect(db.get(first.dn)?.tabs.main?.values.givenName).toBe('Zed')
    expect(db.get(first.dn)?.tabs.main?.values.cn).toContain('Zed')
    expect(db.locks.has(first.dn.toLowerCase())).toBe(false)
  })

  it('handles the second-factor step', async () => {
    renderApp('/')
    await userEvent.type(await screen.findByLabelText('Username'), 'mfa')
    await userEvent.type(screen.getByLabelText('Password'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await userEvent.type(await screen.findByLabelText('Verification code'), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByText(/Welcome/)).toBeInTheDocument()
  })

  it('rejects wrong credentials', async () => {
    renderApp('/')
    await userEvent.type(await screen.findByLabelText('Username'), 'admin')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
  })

  it('renders profile page with identity and rights', async () => {
    renderApp('/me')
    await userEvent.type(await screen.findByLabelText('Username'), 'admin')
    await userEvent.type(screen.getByLabelText('Password'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'My account' })).toBeInTheDocument()
    expect(await screen.findByText('Administrator')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /Edit my account/ })[0]).toBeInTheDocument()
  })

  it('renders 404 empty state for unknown routes', async () => {
    renderApp('/unknown-page')
    expect(await screen.findByText('Not found')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
  })
})

import { screen, waitFor, within } from '@testing-library/react'
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
    expect(await screen.findByText(/1–25 of 200/)).toBeInTheDocument()
    expect(history.location.pathname).toBe('/types/user')

    // open the first user
    const first = db.all('user').sort((a, b) =>
      String(a.tabs.main?.values.uid).localeCompare(String(b.tabs.main?.values.uid), undefined, { numeric: true }),
    )[0]
    if (!first) throw new Error('no users')
    const userLinks = await screen.findAllByRole('link', { name: String(first.tabs.main?.values.cn) })
    await userEvent.click(userLinks[0]!)
    await screen.findByRole('heading', { name: String(first.tabs.main?.values.cn), level: 1 })

    // switch to Details tab for descriptor-driven sections
    await userEvent.click(screen.getByRole('tab', { name: 'Details' }))
    await userEvent.click(screen.getAllByRole('button', { name: /Edit/ })[0]!)

    const given = await screen.findByLabelText(/^First name/)
    await userEvent.clear(given)
    await userEvent.type(given, 'Zed')
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))
    // every save is confirmed on a diff of the changes
    const review = await screen.findByRole('dialog')
    await userEvent.click(within(review).getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(screen.queryByRole('button', { name: /Save/ })).not.toBeInTheDocument())
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
    expect(await screen.findByRole('heading', { name: /^Good (morning|afternoon|evening)/ })).toBeInTheDocument()
  })

  it('drops what an earlier session cached when someone signs in', async () => {
    const { client } = renderApp('/login')
    client.setQueryData(['objects', 'user', 'list', {}], { items: [{ dn: 'uid=previous-user' }] })
    await userEvent.type(await screen.findByLabelText('Username'), 'admin')
    await userEvent.type(screen.getByLabelText('Password'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('heading', { name: /^Good (morning|afternoon|evening)/ })
    expect(client.getQueryData(['objects', 'user', 'list', {}])).toBeUndefined()
  })

  it('does not follow a redirect that leaves the origin', async () => {
    const { history } = renderApp('/login?redirect=%2F%2Fevil.example')
    await userEvent.type(await screen.findByLabelText('Username'), 'admin')
    await userEvent.type(screen.getByLabelText('Password'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('heading', { name: /^Good (morning|afternoon|evening)/ })
    expect(history.location.pathname).toBe('/')
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

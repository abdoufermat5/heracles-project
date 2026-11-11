import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { db } from '@/mocks/db'
import { must, renderApp, signIn, userPath } from '@/test/utils'

// users whose index is not divisible by 3 have no posix tab
async function openEditor() {
  signIn()
  renderApp(`${userPath(4)}?view=generic`)
  await screen.findByRole('heading', { level: 1 })
  await screen.findByLabelText(/^Last name/)
}

describe('editor capabilities', () => {
  beforeEach(() => db.reset())

  it('lists only the main and active tabs, inactive ones go under Add capability', async () => {
    await openEditor()
    expect(screen.queryByRole('tab', { name: /POSIX account/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Inactive')).not.toBeInTheDocument()
    // read-only: the menu is offered but disabled
    expect(screen.getByRole('button', { name: /Add capability/ })).toBeDisabled()
  })

  it('activates a capability from the menu, marks it new, and lets it be removed', async () => {
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    await waitFor(() => expect(screen.getByLabelText(/^Last name/)).toBeEnabled())

    await userEvent.click(screen.getByRole('button', { name: /Add capability/ }))
    const item = await screen.findByRole('menuitem', { name: /POSIX account/ })
    expect(within(item).getByText('Unix account: UID, home directory, shell')).toBeInTheDocument()
    await userEvent.click(item)

    const tab = await screen.findByRole('tab', { name: /POSIX account/ })
    expect(tab).toHaveAttribute('aria-selected', 'true')
    expect(within(tab).getByText('new')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Remove POSIX account' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Remove POSIX account' })).not.toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /Add capability/ }))
    expect(await screen.findByRole('menuitem', { name: /POSIX account/ })).toBeInTheDocument()
  })
})

describe('user profile advanced tab', () => {
  beforeEach(() => db.reset())

  it('splits active and available capabilities with descriptions', async () => {
    signIn()
    const target = must(db.all('user')[4])
    renderApp(`/types/user/${encodeURIComponent(target.dn)}`)
    await screen.findByRole('heading', { level: 1 })
    await userEvent.click(screen.getByRole('tab', { name: 'Advanced' }))
    const available = await screen.findByRole('list', { name: 'Available capabilities' })
    expect(within(available).getByText('POSIX account')).toBeInTheDocument()
    expect(within(available).getByText('Unix account: UID, home directory, shell')).toBeInTheDocument()
    expect(within(available).getByRole('link', { name: 'Set up' })).toBeInTheDocument()
    expect(screen.getByText('Nothing is enabled yet.')).toBeInTheDocument()
  })
})

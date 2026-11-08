import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { db } from '@/mocks/db'
import { must, renderApp, signIn } from '@/test/utils'

describe('Offboarding dialog', () => {
  beforeEach(() => {
    db.reset()
  })

  it('configures and executes offboarding for a user', async () => {
    signIn()
    const target = must(db.all('user')[0])
    renderApp(`/types/user/${encodeURIComponent(target.dn)}`)

    await screen.findByRole('heading', { level: 1 })
    const offboardBtn = screen.getByRole('button', { name: /Offboard/ })
    await userEvent.click(offboardBtn)

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Offboard/)).toBeInTheDocument()
    expect(within(dialog).getByText('Safety snapshot')).toBeInTheDocument()
    expect(within(dialog).getByText('Account access')).toBeInTheDocument()
    expect(within(dialog).getByText('Group memberships')).toBeInTheDocument()

    // Execute offboarding
    const startBtn = within(dialog).getByRole('button', { name: 'Execute offboarding' })
    await userEvent.click(startBtn)

    // Summary view should appear
    expect(await within(dialog).findByText('Offboarding completed')).toBeInTheDocument()
    expect(within(dialog).getByText('Safety snapshot created')).toBeInTheDocument()
    expect(within(dialog).getByText('Account locked')).toBeInTheDocument()

    // Close summary
    await userEvent.click(within(dialog).getAllByRole('button', { name: 'Close' })[0]!)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { renderApp, signIn } from '@/test/utils'

describe('dashboard', () => {
  it('leads with the work queue and opens the locked accounts already filtered', async () => {
    signIn()
    const user = userEvent.setup()
    const { history } = renderApp('/')
    const queue = await screen.findByRole('region', { name: 'Needs attention' })
    const locked = await within(queue).findByText(/locked account/)
    const row = locked.closest('li')
    expect(row).not.toBeNull()
    await user.click(within(row as HTMLElement).getByRole('link', { name: /Review/ }))
    await waitFor(() => expect(history.location.pathname).toBe('/types/user'))
    expect(history.location.search).toContain('filter=locked')
    // the Locked view is selected and every listed person is locked
    await waitFor(() => expect(screen.getAllByText('Locked').length).toBeGreaterThan(1))
    expect(screen.queryByText('Active', { selector: '[data-status]' })).not.toBeInTheDocument()
  })
})

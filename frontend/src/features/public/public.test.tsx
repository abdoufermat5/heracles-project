import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderApp } from '@/test/utils'

describe('public form page', () => {
  it('solves the check in the background, then submits', async () => {
    // The mock server verifies the proof of work like the real one: a wrong counter is a 422.
    const user = userEvent.setup()
    renderApp('/forms/register')
    await user.type(await screen.findByLabelText(/First name/), 'Ada')
    await user.type(screen.getByLabelText(/Last name/), 'Lovelace')
    await user.type(screen.getByLabelText(/Email address/), 'ada@example.org')
    const send = screen.getByRole('button', { name: 'Send' })
    // Enabled only once the proof of work is solved and the minimum fill time has passed.
    await waitFor(() => expect(send).toBeEnabled(), { timeout: 4000 })
    await user.click(send)
    expect(await screen.findByRole('status')).toHaveTextContent('Your account has been created.')
  })

  it('keeps the honeypot out of sight and out of reach', async () => {
    renderApp('/forms/register')
    await screen.findByLabelText(/First name/)
    expect(screen.queryByRole('textbox', { name: /website/i })).not.toBeInTheDocument()
    const trap = screen.getByTestId('honeypot')
    expect(trap).toHaveAttribute('aria-hidden', 'true')
    expect(trap.querySelector('input')).toHaveAttribute('tabindex', '-1')
    expect(trap.querySelector('input')).toHaveAttribute('autocomplete', 'off')
  })

  it('explains that an invitation has expired', async () => {
    renderApp('/forms/join?token=old-token')
    expect(await screen.findByRole('alert')).toHaveTextContent('expired or has already been used')
    expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument()
  })
})

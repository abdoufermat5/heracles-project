import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { db } from '@/mocks/db'
import { renderApp, signIn } from '@/test/utils'

afterEach(() => {
  db.reauthFresh = true
})

describe('authenticator code', () => {
  it('says why the code is not accepted yet and keeps what was typed', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/me')
    await user.click(await screen.findByRole('button', { name: 'Set up authenticator app' }))
    const code = await screen.findByLabelText('Verification code')
    await user.type(code, '123')
    await user.tab()

    expect(
      await screen.findByText('Enter the 6-digit code from your authenticator app.'),
    ).toHaveAttribute('role', 'alert')
    expect(code).toHaveAttribute('aria-invalid', 'true')
    expect(code).toHaveValue('123')
    expect(screen.getByRole('button', { name: 'Verify and enable' })).toBeDisabled()
    expect(db.totp.enabled).toBe(false)
  })
})

describe('confirmation dialog', () => {
  it('refuses a code that is not six digits before asking the server', async () => {
    db.reauthFresh = false
    signIn()
    const user = userEvent.setup()
    renderApp('/me')
    await user.click(await screen.findByRole('button', { name: 'Set up authenticator app' }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.click(dialog.getByRole('button', { name: /Use a code from my authenticator app/ }))

    const field = dialog.getByLabelText('Authenticator or recovery code')
    await user.type(field, '12ab')
    await user.tab()
    expect(
      await dialog.findByText('Enter the 6-digit code from your authenticator app.'),
    ).toHaveAttribute('role', 'alert')
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(field).toHaveValue('12ab')
    expect(dialog.getByRole('button', { name: 'Confirm' })).toHaveAttribute('aria-disabled', 'true')

    await user.click(dialog.getByRole('button', { name: 'Confirm' }))
    expect(db.reauthFresh).toBe(false) // nothing was sent
  })
})

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/mocks/server'
import { renderApp, signIn } from '@/test/utils'

/** Opens the profile editor; the section may re-render while the entry loads, so retry. */
async function editProfile(user: ReturnType<typeof userEvent.setup>) {
  const section = () =>
    within(screen.getByRole('heading', { name: 'My profile' }).closest('section') as HTMLElement)
  await waitFor(async () => {
    if (!section().queryByLabelText('Phone numbers')) await user.click(section().getByRole('button', { name: 'Edit' }))
    expect(section().getByLabelText('Phone numbers')).toBeInTheDocument()
  })
  return section()
}

describe('portal profile form', () => {
  it('refuses a malformed phone number inline and keeps the typed value', async () => {
    signIn('employee')
    const user = userEvent.setup()
    renderApp('/me')
    await screen.findByRole('heading', { name: 'My profile' })
    const form = await editProfile(user)

    const phone = form.getByLabelText('Phone numbers')
    await user.clear(phone)
    await user.type(phone, 'call me')
    await user.tab()

    expect(await form.findByText('Enter a valid phone number')).toHaveAttribute('role', 'alert')
    expect(phone).toHaveAttribute('aria-invalid', 'true')
    expect(phone).toHaveValue('call me')
    expect(form.getByText('Fix 1 invalid field to continue.')).toBeInTheDocument()
    expect(form.getByRole('button', { name: 'Save' })).toBeDisabled()

    await user.clear(phone)
    await user.type(phone, '+33 1 99 88 77 66')
    await waitFor(() => expect(form.getByRole('button', { name: 'Save' })).toBeEnabled())
  })

  it('shows what the server refused under the field, not in a toast', async () => {
    signIn('employee')
    const user = userEvent.setup()
    server.use(
      http.patch('/api/v2/objects/user/:dn', () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation',
              message: 'Validation failed',
              fields: { 'main.telephoneNumber': 'This number is not allowed.' },
            },
          },
          { status: 422 },
        ),
      ),
    )
    renderApp('/me')
    await screen.findByRole('heading', { name: 'My profile' })
    const form = await editProfile(user)
    const phone = form.getByLabelText('Phone numbers')
    await user.clear(phone)
    await user.type(phone, '+33 1 99 88 77 66')
    await user.click(form.getByRole('button', { name: 'Save' }))

    expect(await form.findByText('This number is not allowed.')).toHaveAttribute('role', 'alert')
    expect(phone).toHaveAttribute('aria-invalid', 'true')
    expect(phone).toHaveValue('+33 1 99 88 77 66')
  })
})

describe('portal password form', () => {
  async function open() {
    signIn('employee')
    renderApp('/me')
    const section = (await screen.findByRole('heading', { name: 'Password' })).closest('section') as HTMLElement
    return within(section)
  }

  it('applies the live policy length and blocks the change until the form is valid', async () => {
    server.use(http.get('/api/v2/auth/password-policy', () => HttpResponse.json({ min_length: 12 })))
    const user = userEvent.setup()
    const pw = await open()
    expect(await pw.findByText('Use at least 12 characters.')).toBeInTheDocument()

    const field = pw.getByLabelText('New password')
    await user.type(field, 'elevenchars')
    await user.tab()
    expect(await pw.findByText('Must be at least 12 characters')).toHaveAttribute('role', 'alert')
    expect(field).toHaveAttribute('aria-invalid', 'true')
    await user.type(pw.getByLabelText('Confirm new password'), 'elevenchars')
    expect(pw.getByRole('button', { name: 'Change password' })).toBeDisabled()

    await user.type(field, '+')
    await waitFor(() => expect(pw.queryByText('Must be at least 12 characters')).not.toBeInTheDocument())
  })

  it('says when the confirmation differs and shows the policy verdict under the field', async () => {
    const user = userEvent.setup()
    const pw = await open()
    await user.type(pw.getByLabelText('New password'), 'SuperSecret123!')
    await user.type(pw.getByLabelText('Confirm new password'), 'Other')
    expect(pw.getByText('Passwords do not match.')).toHaveAttribute('role', 'alert')
    expect(pw.getByLabelText('Confirm new password')).toHaveAttribute('aria-invalid', 'true')
    expect(pw.getByRole('button', { name: 'Change password' })).toBeDisabled()

    server.use(
      http.patch('/api/v2/objects/user/:dn', () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation',
              message: 'Validation failed',
              fields: { 'main.userPassword': 'This password is too common.' },
            },
          },
          { status: 422 },
        ),
      ),
    )
    await user.clear(pw.getByLabelText('Confirm new password'))
    await user.type(pw.getByLabelText('Confirm new password'), 'SuperSecret123!')
    await user.click(pw.getByRole('button', { name: 'Change password' }))
    expect(await pw.findByText('This password is too common.')).toHaveAttribute('role', 'alert')
    expect(pw.getByLabelText('New password')).toHaveValue('SuperSecret123!')
  })
})

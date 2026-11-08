import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { describe, expect, it } from 'vitest'
import { setTechnicalDetails } from '@/lib/preferences'
import { renderApp, signIn } from '@/test/utils'

describe('employee self-service portal', () => {
  it('renders portal home for employee with friendly greeting, profile, and groups', async () => {
    act(() => setTechnicalDetails(false))
    signIn('employee')
    renderApp('/me')

    // Friendly greeting without admin jargon
    expect(await screen.findByText(/Hello, Emma/)).toBeInTheDocument()
    expect(screen.getByText('Manage your profile, password, and account security.')).toBeInTheDocument()

    // Profile card displays details and readable department path
    expect(screen.getByText('emma.employee@example.com')).toBeInTheDocument()
    expect(screen.getByText('Paris › Engineering')).toBeInTheDocument()

    // My Groups displays the groups the employee belongs to
    expect(await screen.findByRole('heading', { name: /My groups/ })).toBeInTheDocument()
    expect(await screen.findByText('staff')).toBeInTheDocument()
    expect(screen.getByText('developers')).toBeInTheDocument()

    // No technical DNs visible to employee
    expect(screen.queryByText(/ou=people,ou=Engineering/)).not.toBeInTheDocument()
  })

  it('allows employee to inline-edit permitted profile fields', async () => {
    signIn('employee')
    const user = userEvent.setup()
    renderApp('/me')

    const profileHeading = await screen.findByRole('heading', { name: 'My profile' })
    const profileSection = profileHeading.closest('section') as HTMLElement
    expect(profileSection).not.toBeNull()

    // Click Edit button on the SectionCard
    const editBtn = within(profileSection).getByRole('button', { name: 'Edit' })
    await user.click(editBtn)

    // Form inputs appear for editable fields
    const phoneInput = within(profileSection).getByLabelText('Phone')
    await user.clear(phoneInput)
    await user.type(phoneInput, '+33 1 99 88 77 66')

    // Save changes
    const saveBtn = within(profileSection).getByRole('button', { name: 'Save' })
    await user.click(saveBtn)

    // Should return to view mode with updated value
    await waitFor(() => {
      expect(within(profileSection).queryByRole('textbox', { name: 'Phone' })).not.toBeInTheDocument()
    })
    expect(within(profileSection).getByText('+33 1 99 88 77 66')).toBeInTheDocument()
  })

  it('validates password policy and changes password', async () => {
    signIn('employee')
    const user = userEvent.setup()
    renderApp('/me')

    const pwdHeading = await screen.findByRole('heading', { name: 'Password' })
    const pwdSection = pwdHeading.closest('section') as HTMLElement
    expect(pwdSection).not.toBeNull()

    const newPwdInput = within(pwdSection).getByLabelText('New password')
    const confirmPwdInput = within(pwdSection).getByLabelText('Confirm new password')
    const submitBtn = within(pwdSection).getByRole('button', { name: 'Change password' })

    // Initially button is disabled
    expect(submitBtn).toBeDisabled()

    // Mismatching passwords: button disabled and mismatch alert shown
    await user.type(newPwdInput, 'SuperSecret123!')
    await user.type(confirmPwdInput, 'DifferentSecret456!')
    expect(submitBtn).toBeDisabled()
    expect(within(pwdSection).getByText('Passwords do not match.')).toBeInTheDocument()

    // Matching passwords: submit enabled
    await user.clear(confirmPwdInput)
    await user.type(confirmPwdInput, 'SuperSecret123!')
    expect(submitBtn).toBeEnabled()
    await user.click(submitBtn)

    // Should succeed and reset fields
    await waitFor(() => {
      expect(newPwdInput).toHaveValue('')
      expect(confirmPwdInput).toHaveValue('')
    })
  })

  it('shows technical details card for console user only when preference is enabled', async () => {
    signIn() // Admin user
    const { unmount } = renderApp('/me')

    // Turn technical details ON
    act(() => setTechnicalDetails(true))
    const techHeading = await screen.findByRole('heading', { name: 'Technical details' })
    const techSection = techHeading.closest('section') as HTMLElement
    expect(within(techSection).getByText('uid=admin,ou=people,dc=example,dc=com')).toBeInTheDocument()

    unmount()

    // Turn technical details OFF
    act(() => setTechnicalDetails(false))
    renderApp('/me')
    expect(await screen.findByRole('heading', { name: 'My profile' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Technical details' })).not.toBeInTheDocument()
  })
})

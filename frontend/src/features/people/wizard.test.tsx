import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { db } from '@/mocks/db'
import { renderApp, signIn } from '@/test/utils'

describe('Create user wizard', () => {
  beforeEach(() => {
    db.reset()
  })

  it('progresses through steps 1-4 and creates a new user', async () => {
    signIn()
    renderApp('/types/user/new')

    expect(await screen.findByRole('heading', { name: 'New person', level: 1 })).toBeInTheDocument()

    // Step 1: Identity
    const firstName = screen.getByLabelText(/First name/)
    const lastName = screen.getByLabelText(/Last name/)
    const login = screen.getByLabelText(/Login \(username\)/)
    const email = screen.getByLabelText(/Email address/)

    await userEvent.type(firstName, 'Claire')
    await userEvent.type(lastName, 'Danvers')

    // Suggestions should be populated
    expect(login).toHaveValue('cdanvers')
    expect(email).toHaveValue('cdanvers@example.com')

    // Next step
    const nextBtn = screen.getByRole('button', { name: 'Next step' })
    await userEvent.click(nextBtn)

    // Step 2: Department & Groups
    expect(await screen.findByText('Assign to groups')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Next step' }))

    // Step 3: Password
    expect(await screen.findByText('Generate strong password')).toBeInTheDocument()
    const genBtn = screen.getByRole('button', { name: 'Generate strong password' })
    await userEvent.click(genBtn)

    const pwInput = screen.getByPlaceholderText('Enter or generate initial password')
    expect(pwInput).not.toHaveValue('')

    await userEvent.click(screen.getByRole('button', { name: 'Next step' }))

    // Step 4: Review & Create
    expect(await screen.findByText('Account summary')).toBeInTheDocument()
    expect(screen.getByText('Claire Danvers')).toBeInTheDocument()
    expect(screen.getByText('cdanvers')).toBeInTheDocument()

    const createBtn = screen.getByRole('button', { name: 'Create user' })
    await userEvent.click(createBtn)

    // Should navigate to user profile
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Claire Danvers', level: 1 })).toBeInTheDocument()
    })
  })
})

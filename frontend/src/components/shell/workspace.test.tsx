import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { renderApp, signIn } from '@/test/utils'

afterEach(() => {
  localStorage.removeItem('heracles.technicalDetails')
})

describe('workspace shell', () => {
  it('gives people who only manage themselves the portal, at their account page', async () => {
    signIn('employee')
    const { history } = renderApp('/')
    await waitFor(() => expect(history.location.pathname).toBe('/me'))
    expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument()
    expect(screen.getAllByText('My account').length).toBeGreaterThan(0)
  })

  it('keeps portal users away from console pages', async () => {
    signIn('employee')
    const { history } = renderApp('/types/user')
    await waitFor(() => expect(history.location.pathname).toBe('/me'))
  })

  it('groups the console navigation by task', async () => {
    signIn()
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    await waitFor(() => expect(nav).toHaveTextContent('People'))
    expect(nav).toHaveTextContent('Organization')
  })

  it('shows technical details by default in the console and remembers the choice', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/')
    await user.click(await screen.findByRole('button', { name: 'User menu' }))
    const item = await screen.findByRole('menuitemcheckbox', { name: 'Show technical details' })
    expect(item).toHaveAttribute('aria-checked', 'true')
    await user.click(item)
    expect(localStorage.getItem('heracles.technicalDetails')).toBe('0')
  })
})

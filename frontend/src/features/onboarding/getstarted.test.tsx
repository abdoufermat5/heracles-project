import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { renderApp, signIn } from '@/test/utils'

describe('get started checklist', () => {
  it('lists the first steps for an administrator and remembers ticks and dismissal', async () => {
    signIn()
    const user = userEvent.setup()
    const first = renderApp('/')
    const card = await screen.findByRole('region', { name: 'Get started' })
    expect(card).toBeInTheDocument()

    await user.click(await screen.findByRole('checkbox', { name: /Review the plugins/ }))
    await waitFor(() => expect(localStorage.getItem('heracles.getstarted.admin')).toContain('plugins'))

    await user.click(screen.getByRole('button', { name: 'Dismiss the getting started checklist' }))
    expect(screen.queryByRole('region', { name: 'Get started' })).not.toBeInTheDocument()
    first.unmount()

    renderApp('/')
    await screen.findByRole('region', { name: 'Needs attention' })
    expect(screen.queryByRole('region', { name: 'Get started' })).not.toBeInTheDocument()
  })
})

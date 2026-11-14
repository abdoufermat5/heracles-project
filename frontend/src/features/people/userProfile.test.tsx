import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BASE_DN, db } from '@/mocks/db'
import { server } from '@/mocks/server'
import { must, renderApp, signIn } from '@/test/utils'

describe('User profile page', () => {
  beforeEach(() => {
    db.reset()
  })

  it('renders entity header, status badge, and overview tab facts', async () => {
    signIn()
    const target = must(db.all('user')[0])
    renderApp(`/types/user/${encodeURIComponent(target.dn)}`)

    const name = String(target.tabs.main?.values.cn)
    expect(await screen.findByRole('heading', { name, level: 1 })).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Details' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Access' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Security' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Advanced' })).toBeInTheDocument()

    // Key facts
    expect(screen.getByText('Identity & Account')).toBeInTheDocument()
    expect(screen.getAllByText(String(target.tabs.main?.values.uid)).length).toBeGreaterThan(0)
  })

  it('switches to Details tab and allows SectionCard inline editing', async () => {
    signIn()
    const target = must(db.all('user')[0])
    renderApp(`/types/user/${encodeURIComponent(target.dn)}`)

    await screen.findByRole('heading', { level: 1 })
    await userEvent.click(screen.getByRole('tab', { name: 'Details' }))

    // Identity section card edit button
    const editBtns = screen.getAllByRole('button', { name: 'Edit' })
    expect(editBtns.length).toBeGreaterThan(0)
    await userEvent.click(editBtns[0]!)

    // Save and Cancel buttons appear
    expect(await screen.findByRole('button', { name: 'Save' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    // Canceling exits edit mode
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
  })

  it('opens and uses reset password dialog', async () => {
    signIn()
    const target = must(db.all('user')[0])
    renderApp(`/types/user/${encodeURIComponent(target.dn)}`)

    await screen.findByRole('heading', { level: 1 })
    const resetBtn = screen.getByRole('button', { name: 'Reset password' })
    await userEvent.click(resetBtn)

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Reset password for/)).toBeInTheDocument()

    // Generate password
    const genBtn = within(dialog).getByRole('button', { name: 'Generate password' })
    await userEvent.click(genBtn)

    const pwInput = within(dialog).getByPlaceholderText('Enter a strong password')
    expect(pwInput).not.toHaveValue('')

    // Save password
    const submitBtn = within(dialog).getByRole('button', { name: 'Save password' })
    await userEvent.click(submitBtn)

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('toggles lock on the user account', async () => {
    signIn()
    const target = must(db.all('user')[0])
    renderApp(`/types/user/${encodeURIComponent(target.dn)}`)

    await screen.findByRole('heading', { level: 1 })
    const lockBtn = screen.getByRole('button', { name: 'Lock account' })
    await userEvent.click(lockBtn)

    expect(await screen.findByRole('button', { name: 'Unlock account' })).toBeInTheDocument()
  })

  it('opens delete dialog and requires typing login to confirm', async () => {
    signIn()
    const target = must(db.all('user')[0])
    const uid = String(target.tabs.main?.values.uid)
    renderApp(`/types/user/${encodeURIComponent(target.dn)}`)

    await screen.findByRole('heading', { level: 1 })
    await userEvent.click(screen.getByRole('button', { name: 'More actions' }))
    await userEvent.click(screen.getByRole('menuitem', { name: /Delete user/ }))

    const alert = await screen.findByRole('alertdialog')
    expect(within(alert).getByText(new RegExp(`Delete ${target.tabs.main?.values.cn}`))).toBeInTheDocument()

    const confirmBtn = within(alert).getByRole('button', { name: 'Delete user' })
    expect(confirmBtn).toBeDisabled()

    // Type login
    const input = within(alert).getByRole('textbox')
    await userEvent.type(input, uid)
    expect(confirmBtn).not.toBeDisabled()

    await userEvent.click(within(alert).getByRole('button', { name: 'Cancel' }))
  })
})

describe('missing object', () => {
  it('issues no reference, snapshot or second-factor request', async () => {
    signIn()
    const seen: string[] = []
    const listener = ({ request }: { request: Request }) => {
      const path = new URL(request.url).pathname
      if (/\/(references|snapshots|second-factors)$/.test(path)) seen.push(path)
    }
    server.events.on('request:start', listener)

    renderApp(`/types/user/${encodeURIComponent(`uid=ghost,ou=people,${BASE_DN}`)}`)
    expect(await screen.findByText('Not found')).toBeInTheDocument()

    expect(seen).toEqual([])
    server.events.removeListener('request:start', listener)
  })
})

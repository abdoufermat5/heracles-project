import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { db } from '@/mocks/db'
import { must, renderApp, signIn } from '@/test/utils'

describe('Group profile page', () => {
  beforeEach(() => {
    db.reset()
  })

  it('renders group entity header, member list, and allows member removal', async () => {
    signIn()
    const target = must(db.all('group')[0])
    renderApp(`/types/group/${encodeURIComponent(target.dn)}`)

    const groupName = String(target.tabs.main?.values.cn)
    expect(await screen.findByRole('heading', { name: groupName, level: 1 })).toBeInTheDocument()

    // Members tab
    expect(screen.getByRole('tab', { name: 'Members' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Properties' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Advanced' })).toBeInTheDocument()

    // Table of members
    const removeBtns = await screen.findAllByRole('button', { name: 'Remove member' })
    expect(removeBtns.length).toBeGreaterThan(0)

    // Remove first member
    await userEvent.click(removeBtns[0]!)
    const confirmDialog = await screen.findByRole('alertdialog')
    expect(within(confirmDialog).getByText(/Remove group member/)).toBeInTheDocument()

    await userEvent.click(within(confirmDialog).getByRole('button', { name: 'Remove member' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  })

  it('opens add members dialog and adds selected user to group', async () => {
    signIn()
    const target = must(db.all('group')[0])
    renderApp(`/types/group/${encodeURIComponent(target.dn)}`)

    await screen.findByRole('heading', { level: 1 })
    const addBtns = screen.getAllByRole('button', { name: 'Add members' })
    await userEvent.click(addBtns[0]!)

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Add members to/)).toBeInTheDocument()

    // Find and select a user
    const checkboxes = within(dialog).getAllByRole('checkbox')
    expect(checkboxes.length).toBeGreaterThan(0)
    await userEvent.click(checkboxes[0]!)

    // Submit add
    const submitBtn = within(dialog).getByRole('button', { name: 'Add to group' })
    expect(submitBtn).not.toBeDisabled()
    await userEvent.click(submitBtn)

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('gives a member an end date and removes it again', async () => {
    signIn()
    const user = userEvent.setup()
    const target = must(db.all('group')[0])
    renderApp(`/types/group/${encodeURIComponent(target.dn)}`)
    const buttons = await screen.findAllByRole('button', { name: /^Set end date for / })
    await user.click(buttons[0]!)
    const dialog = await screen.findByRole('dialog')
    const next = new Date(Date.now() + 10 * 86_400_000).toISOString().slice(0, 10)
    await user.type(within(dialog).getByLabelText('Last day of access'), next)
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(`Until ${next}`)).toBeInTheDocument()
    expect(db.endDates).toHaveLength(1)

    await user.click((await screen.findAllByRole('button', { name: /^Set end date for / }))[0]!)
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Remove end date' }))
    await waitFor(() => expect(screen.queryByText(`Until ${next}`)).not.toBeInTheDocument())
    expect(db.endDates).toHaveLength(0)
  })
})

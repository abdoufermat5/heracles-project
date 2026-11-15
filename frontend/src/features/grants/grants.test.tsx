import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { db } from '@/mocks/db'
import { must, renderApp, signIn } from '@/test/utils'

describe('access requests', () => {
  beforeEach(() => db.reset())

  it('lets an employee request access from the portal', async () => {
    signIn('employee')
    const user = userEvent.setup()
    renderApp('/me')
    await screen.findByText('You have not requested any access.')
    await user.click(screen.getByRole('button', { name: 'Request access' }))
    const dialog = await screen.findByRole('dialog')
    // nothing chosen yet: the form says what is missing
    await user.click(within(dialog).getByRole('button', { name: 'Send request' }))
    expect(await within(dialog).findByText('Choose what you need')).toBeInTheDocument()
    expect(within(dialog).getByText('Say why you need this access')).toBeInTheDocument()

    const select = within(dialog).getByLabelText('Group or role') as HTMLSelectElement
    const option = must(Array.from(select.options).find((o) => o.value))
    await user.selectOptions(select, option.value)
    await user.type(within(dialog).getByLabelText('Why do you need it?'), 'New project')
    const next = new Date(Date.now() + 20 * 86_400_000).toISOString().slice(0, 10)
    await user.type(within(dialog).getByLabelText('Until'), next)
    await user.click(within(dialog).getByRole('button', { name: 'Send request' }))
    await waitFor(() => expect(db.accessRequests).toHaveLength(1))
    expect(await screen.findByText('Waiting for approval', { exact: false })).toBeInTheDocument()
    expect(db.accessRequests[0]?.reason).toBe('New project')
  })

  it('shows pending requests on the dashboard and lets an approver decide', async () => {
    db.accessRequests.push({
      id: 'r1',
      requester: 'uid=employee,ou=people,dc=example,dc=org',
      member: 'uid=employee,ou=people,dc=example,dc=org',
      target: { dn: 'cn=devs,ou=groups,dc=example,dc=org', kind: 'member', label: 'devs' },
      reason: 'On call',
      until: null,
      status: 'pending',
      created_at: Date.now() / 1000,
      decided_by: '',
      decided_at: null,
      comment: '',
      error: '',
    })
    signIn()
    const user = userEvent.setup()
    renderApp('/')
    expect(await screen.findByText('access request to approve')).toBeInTheDocument()
    const item = must(screen.getByText('access request to approve').closest('li'))
    await user.click(within(item).getByRole('link'))
    expect(await screen.findByRole('heading', { name: 'Access requests', level: 1 })).toBeInTheDocument()
    expect(screen.getByText('employee asks to join devs')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Reject' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Reject' }))
    expect(await within(dialog).findByText('Say why the request is rejected')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    await user.click(screen.getByRole('button', { name: 'Approve' }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(db.accessRequests[0]?.status).toBe('approved'))
    expect(await screen.findByText('Nothing waits for your decision.')).toBeInTheDocument()
  })
})

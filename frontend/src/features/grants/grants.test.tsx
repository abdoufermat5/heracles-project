import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { adminMock } from '@/mocks/adminHandlers'
import { db } from '@/mocks/db'
import { server } from '@/mocks/server'
import { must, renderApp, signIn } from '@/test/utils'
import { accessApi } from './api'

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

describe('access reviews', () => {
  beforeEach(() => db.reset())

  it('starts a review, records decisions and closes it', async () => {
    db.campaigns.push({
      id: 'c1',
      name: 'Q4 review',
      created_by: 'uid=admin,dc=example,dc=org',
      created_at: Date.now() / 1000,
      deadline: Date.now() / 1000 + 7 * 86_400,
      reviewer: 'owner',
      default: 'keep',
      status: 'open',
      selector: { holders: [], base: '' },
      closed_by: '',
      closed_at: null,
      report_hash: '',
    })
    db.reviewItems.push({
      campaign: 'c1',
      id: 'i1',
      holder: { dn: 'cn=devs,ou=groups,dc=example,dc=org', label: 'devs', kind: 'member' },
      member: 'uid=jdoe,ou=people,dc=example,dc=org',
      reviewer: 'uid=admin,dc=example,dc=org',
      decision: '',
      comment: '',
      decided_by: '',
      decided_at: null,
      outcome: '',
      can_decide: true,
    })
    signIn()
    const user = userEvent.setup()
    renderApp('/')
    const item = must((await screen.findByText('access grant to review')).closest('li'))
    await user.click(within(item).getByRole('link'))
    await user.click(await screen.findByRole('link', { name: 'Q4 review' }))
    expect(await screen.findByRole('heading', { name: 'Q4 review', level: 1 })).toBeInTheDocument()
    const row = await screen.findByTestId('review-item')
    await user.click(within(row).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(db.reviewItems[0]?.decision).toBe('revoke'))
    expect(await within(row).findByRole('button', { name: 'Remove', pressed: true })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Close review' }))
    const confirm = await screen.findByRole('alertdialog')
    expect(within(confirm).getByText(/1 access grants are removed now/)).toBeInTheDocument()
    await user.click(within(confirm).getByRole('button', { name: 'Close review' }))
    expect(await screen.findByText('Removed')).toBeInTheDocument()
    expect(screen.getByText('ab'.repeat(32))).toBeInTheDocument()
  })

  it('asks for the password before downloading a report with an old sign-in', async () => {
    db.campaigns.push({
      id: 'c2',
      name: 'Old one',
      created_by: '',
      created_at: 0,
      deadline: Date.now() / 1000 + 86_400,
      reviewer: 'owner',
      default: 'keep',
      status: 'closed',
      selector: { holders: [], base: '' },
      closed_by: '',
      closed_at: null,
      report_hash: 'ab'.repeat(32),
    })
    db.reauthFresh = false
    signIn()
    const user = userEvent.setup()
    renderApp('/access/reviews/c2')
    await user.click(await screen.findByRole('button', { name: /Report/ }))
    await user.click(await screen.findByRole('menuitem', { name: 'JSON (with hash)' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Downloading a review report needs a recent sign-in/)).toBeInTheDocument()
  })
})

describe('without the access plugin', () => {
  beforeEach(() => db.reset())

  it('only probes the status, and shows nothing of it', async () => {
    const calls: string[] = []
    const listen = ({ request }: { request: Request }) => {
      const path = new URL(request.url).pathname
      if (path.startsWith('/api/v2/access')) calls.push(path)
    }
    server.events.on('request:start', listen)
    server.use(
      http.get('/api/v2/access/status', () =>
        HttpResponse.json({ error: { code: 'not_found', message: 'Not found' } }, { status: 404 }),
      ),
    )
    signIn()
    const target = must(db.all('group')[0])
    renderApp(`/types/group/${encodeURIComponent(target.dn)}`)
    await screen.findAllByRole('button', { name: 'Remove member' })
    expect(screen.queryByRole('button', { name: /^Set end date for / })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Access requests' })).not.toBeInTheDocument()
    server.events.removeListener('request:start', listen)
    expect(new Set(calls)).toEqual(new Set(['/api/v2/access/status']))
  })
})

describe('requests for someone else', () => {
  beforeEach(() => db.reset())

  const futureDay = () => new Date(Date.now() + 20 * 86_400_000).toISOString().slice(0, 10)

  async function fillRequest(dialog: HTMLElement, user: ReturnType<typeof userEvent.setup>) {
    const select = within(dialog).getByLabelText('Group or role') as HTMLSelectElement
    await user.selectOptions(select, must(Array.from(select.options).find((o) => o.value)).value)
    await user.type(within(dialog).getByLabelText('Why do you need it?'), 'Joins the project')
    await user.type(within(dialog).getByLabelText('Until'), futureDay())
  }

  async function pickPerson(
    dialog: HTMLElement,
    user: ReturnType<typeof userEvent.setup>,
    person: ReturnType<typeof db.all>[number],
  ) {
    await user.click(await within(dialog).findByRole('combobox', { name: 'For' }))
    await user.type(await screen.findByRole('textbox', { name: 'Search…' }), String(person.tabs.main?.values.uid))
    await user.click(await screen.findByText(person.dn))
  }

  it('lets a console user pick the person the access is for', async () => {
    signIn()
    const person = must(db.all('user')[3])
    const requestable = vi.spyOn(accessApi, 'requestable')
    const user = userEvent.setup()
    renderApp('/access/requests')
    await user.click(await screen.findByRole('button', { name: 'Request access' }))
    const dialog = await screen.findByRole('dialog')
    await pickPerson(dialog, user, person)
    expect(within(dialog).getByTestId('req-member-chosen')).toHaveTextContent(String(person.tabs.main?.values.uid))
    // the choices are those of the person, not of the caller
    await waitFor(() => expect(requestable).toHaveBeenCalledWith(person.dn, expect.anything()))
    await fillRequest(dialog, user)
    await user.click(within(dialog).getByRole('button', { name: 'Send request' }))
    await waitFor(() => expect(db.accessRequests).toHaveLength(1))
    expect(db.accessRequests[0]?.member).toBe(person.dn)
    expect(db.accessRequests[0]?.requester).toBe(must(db.me()).dn)
  })

  it('asks for oneself when nobody is picked, and sends no member', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/access/requests')
    await user.click(await screen.findByRole('button', { name: 'Request access' }))
    const dialog = await screen.findByRole('dialog')
    await fillRequest(dialog, user)
    await user.click(within(dialog).getByRole('button', { name: 'Send request' }))
    await waitFor(() => expect(db.accessRequests).toHaveLength(1))
    expect(db.accessRequests[0]?.member).toBe(must(db.me()).dn)
  })

  it('offers no picker to an employee who manages nobody', async () => {
    signIn('employee')
    const answered = new Promise<void>((resolve) => {
      const done = ({ request }: { request: Request }) => {
        if (new URL(request.url).searchParams.get('filter')?.startsWith('(manager=')) {
          server.events.removeListener('response:mocked', done)
          resolve()
        }
      }
      server.events.on('response:mocked', done)
    })
    const user = userEvent.setup()
    renderApp('/me')
    await screen.findByText('You have not requested any access.')
    await user.click(screen.getByRole('button', { name: 'Request access' }))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByLabelText('Group or role')
    await answered // the check "does this person manage anyone" came back empty
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(within(dialog).queryByRole('combobox', { name: 'For' })).not.toBeInTheDocument()
    expect(within(dialog).queryByText('Someone else…')).not.toBeInTheDocument()
  })

  it('offers the picker to a manager, and shows the refusal for someone else’s report', async () => {
    signIn('employee')
    const employeeDn = must(db.me()).dn
    const report = must(db.all('user')[0])
    must(report.tabs.main).values.manager = employeeDn
    const stranger = must(db.all('user')[1])
    const user = userEvent.setup()
    renderApp('/me')
    await screen.findByText('You have not requested any access.')
    await user.click(screen.getByRole('button', { name: 'Request access' }))
    const dialog = await screen.findByRole('dialog')
    await pickPerson(dialog, user, stranger)
    await fillRequest(dialog, user)
    await user.click(within(dialog).getByRole('button', { name: 'Send request' }))
    expect(await within(dialog).findByText('You cannot request access for this person')).toBeInTheDocument()
    expect(db.accessRequests).toHaveLength(0)

    await user.click(within(dialog).getByRole('button', { name: 'Request for myself' }))
    await pickPerson(dialog, user, report)
    // the choices follow the person: pick the group again
    const select = within(dialog).getByLabelText('Group or role') as HTMLSelectElement
    await waitFor(() => expect(select.options.length).toBeGreaterThan(1))
    await user.selectOptions(select, must(Array.from(select.options).find((o) => o.value)).value)
    await user.click(within(dialog).getByRole('button', { name: 'Send request' }))
    await waitFor(() => expect(db.accessRequests).toHaveLength(1))
    expect(db.accessRequests[0]?.member).toBe(report.dn)
  })
})

describe('end dates of role occupants', () => {
  beforeEach(() => {
    db.reset()
    adminMock.reset()
  })

  it('dates an occupant from the role’s “Access ends” tab without saving the role', async () => {
    signIn()
    const role = must(db.all('role')[0])
    const occupant = must((role.tabs.main?.values.roleOccupant as string[])[0])
    const name = occupant.split(',')[0]?.split('=')[1] ?? occupant
    const writes: string[] = []
    const listen = ({ request }: { request: Request }) => {
      if (request.method === 'PATCH' && new URL(request.url).pathname.startsWith('/api/v2/objects/')) writes.push(request.method)
    }
    server.events.on('request:start', listen)
    const user = userEvent.setup()
    renderApp(`/types/role/${encodeURIComponent(role.dn)}`)
    // an edit in progress: a submit reaching the editor's form would open its review dialog
    await user.click(await screen.findByRole('button', { name: 'Edit' }))
    await user.type(await screen.findByLabelText('Description'), ' (updated)')
    await user.click(await screen.findByRole('tab', { name: 'Access ends' }))
    const row = must((await screen.findByText(name)).closest('tr'))
    expect(within(row).getByText('No end date')).toBeInTheDocument()

    await user.click(within(row).getByRole('button', { name: `Set end date for ${name}` }))
    const dialog = await screen.findByRole('dialog')
    const day = new Date(Date.now() + 10 * 86_400_000).toISOString().slice(0, 10)
    await user.type(within(dialog).getByLabelText('Last day of access'), day)
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(db.endDates).toHaveLength(1))
    expect(db.endDates[0]).toMatchObject({ holder: role.dn, kind: 'roleOccupant', member: occupant })
    expect(await within(row).findByText(`Until ${day}`)).toBeInTheDocument()
    // the dialog's submit must not reach the role form behind it
    expect(writes).toEqual([])
    expect(screen.queryByText('Review changes before saving')).not.toBeInTheDocument()

    await user.click(within(row).getByRole('button', { name: `Set end date for ${name}` }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Remove end date' }))
    await waitFor(() => expect(db.endDates).toHaveLength(0))
    expect(await within(row).findByText('No end date')).toBeInTheDocument()
    server.events.removeListener('request:start', listen)
  })

  it('has no such tab without the access plugin', async () => {
    server.use(
      http.get('/api/v2/access/status', () =>
        HttpResponse.json({ error: { code: 'not_found', message: 'Not found' } }, { status: 404 }),
      ),
    )
    signIn()
    const role = must(db.all('role')[0])
    renderApp(`/types/role/${encodeURIComponent(role.dn)}`)
    await screen.findByRole('tab', { name: 'References' })
    expect(screen.queryByRole('tab', { name: 'Access ends' })).not.toBeInTheDocument()
  })
})

describe('end dates of ACL assignments', () => {
  beforeEach(() => {
    db.reset()
    adminMock.reset()
  })

  it('dates one member of an assignment from “Who has access”', async () => {
    signIn()
    const entry = must(Object.entries(adminMock.assignments)[0])
    const assignment = must(entry[1][0])
    const user = userEvent.setup()
    renderApp('/admin/access')
    await user.click(await screen.findByRole('tab', { name: 'Who has access' }))
    const row = must((await screen.findByText('admins')).closest('li'))
    // nobody is dated yet; the wildcard row has no date button
    expect(within(row).queryByText(/^Until /)).not.toBeInTheDocument()
    expect(within(must(screen.getByText('Every user').closest('li'))).queryByRole('button', { name: /^Set end date/ })).toBeNull()

    await user.click(within(row).getByRole('button', { name: 'Set end date for admins' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/loses this access automatically/)).toBeInTheDocument()
    const day = new Date(Date.now() + 30 * 86_400_000).toISOString().slice(0, 10)
    await user.type(within(dialog).getByLabelText('Last day of access'), day)
    await user.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(db.endDates).toHaveLength(1))
    expect(db.endDates[0]).toMatchObject({
      holder: entry[0],
      kind: 'acl',
      acl_scope: assignment.scope,
      acl_role: assignment.role,
    })
    expect(await within(row).findByText(`Until ${day}`)).toBeInTheDocument()
    // the matrix saved nothing: dating is its own call
    expect(adminMock.requests.filter((r) => r.method === 'PUT')).toHaveLength(0)
  })

  it('shows no date control without the access plugin', async () => {
    server.use(
      http.get('/api/v2/access/status', () =>
        HttpResponse.json({ error: { code: 'not_found', message: 'Not found' } }, { status: 404 }),
      ),
    )
    signIn()
    const user = userEvent.setup()
    renderApp('/admin/access')
    await user.click(await screen.findByRole('tab', { name: 'Who has access' }))
    await screen.findByText('admins')
    expect(screen.queryByRole('button', { name: /^Set end date for / })).not.toBeInTheDocument()
  })
})

describe('access api paths', () => {
  it('encodes every dynamic path segment so an id cannot escape its route', async () => {
    const seen: string[] = []
    server.use(
      http.all('/api/v2/*', ({ request }) => {
        seen.push(new URL(request.url).pathname)
        return HttpResponse.json({})
      }),
    )
    await accessApi.campaign('../../admin/config?x=1#')
    await accessApi.decideItem('a/b', '../c', 'approve', '')
    await accessApi.approve('x/../y', '')
    expect(seen.filter((p) => !p.endsWith('/auth/csrf'))).toEqual([
      '/api/v2/access/reviews/..%2F..%2Fadmin%2Fconfig%3Fx%3D1%23',
      '/api/v2/access/reviews/a%2Fb/items/..%2Fc',
      '/api/v2/access/requests/x%2F..%2Fy/approve',
    ])
  })
})

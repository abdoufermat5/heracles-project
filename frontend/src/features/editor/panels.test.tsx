import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { api } from '@/api/endpoints'
import { db } from '@/mocks/db'
import { server } from '@/mocks/server'
import { must, renderApp, signIn, userDn, userPath } from '@/test/utils'

async function openEditor(path = userPath(0)) {
  signIn()
  renderApp(path)
  await screen.findByRole('heading', { level: 1 })
  await screen.findByLabelText(/^Last name/)
}

describe('references panel', () => {
  it('lists the objects that point to this one, with links', async () => {
    await openEditor()
    await userEvent.click(screen.getByRole('tab', { name: 'References' }))
    const panel = await screen.findByRole('tabpanel')
    const group = await within(panel).findByRole('link', { name: 'admins' })
    expect(group).toHaveAttribute('href', expect.stringContaining('/types/group/'))
    expect(within(panel).getAllByText('member').length).toBeGreaterThan(0)
  })

  it('says when nothing refers to the object', async () => {
    await openEditor(`/types/user/${encodeURIComponent(must(db.all('user')[150]).dn)}`)
    await userEvent.click(screen.getByRole('tab', { name: 'References' }))
    expect(await screen.findByText('Nothing refers to this object.')).toBeInTheDocument()
  })

  it('shows the error when the references cannot be loaded', async () => {
    server.use(
      http.get('/api/v2/objects/:type/:dn/references', () =>
        HttpResponse.json({ error: { code: 'forbidden', message: 'No access' } }, { status: 403 }),
      ),
    )
    await openEditor()
    await userEvent.click(screen.getByRole('tab', { name: 'References' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('No access')
  })

  it('is not offered when creating an object', async () => {
    signIn()
    renderApp('/types/user/new')
    await screen.findByLabelText(/^Login/)
    expect(screen.queryByRole('tab', { name: 'References' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Snapshots' })).not.toBeInTheDocument()
  })
})

describe('snapshots panel', () => {
  it('adds no form of its own inside the editor form', async () => {
    // Nested forms make the browser submit the outer form: the page reloads and
    // the snapshot is never taken.
    await openEditor()
    await userEvent.click(screen.getByRole('tab', { name: 'Snapshots' }))
    await screen.findByText('No snapshots yet.')
    expect(document.querySelectorAll('form')).toHaveLength(1)
  })

  it('takes, restores and deletes snapshots with confirmation', async () => {
    await openEditor()
    await userEvent.click(screen.getByRole('tab', { name: 'Snapshots' }))
    expect(await screen.findByText('No snapshots yet.')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Description'), 'before the move')
    await userEvent.click(screen.getByRole('button', { name: 'Take a snapshot' }))
    const row = (await screen.findByText('before the move')).closest('tr')
    expect(row).not.toBeNull()
    expect(screen.queryByText('No snapshots yet.')).not.toBeInTheDocument()

    // restore (confirmed)
    await userEvent.click(within(row as HTMLElement).getByRole('button', { name: 'Restore' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('Restore this snapshot?')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Restore' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())

    // delete (confirmed)
    await userEvent.click(within(row as HTMLElement).getByRole('button', { name: 'Delete' }))
    const confirm = await screen.findByRole('alertdialog')
    await userEvent.click(within(confirm).getByRole('button', { name: 'Delete' }))
    expect(await screen.findByText('No snapshots yet.')).toBeInTheDocument()
    expect(db.snapshots.size).toBe(0)
  })

  it('reloads the object after a restore', async () => {
    const get = vi.spyOn(api, 'getObject')
    await openEditor()
    await userEvent.click(screen.getByRole('tab', { name: 'Snapshots' }))
    await userEvent.type(await screen.findByLabelText('Description'), 'v1')
    await userEvent.click(screen.getByRole('button', { name: 'Take a snapshot' }))
    const row = (await screen.findByText('v1')).closest('tr') as HTMLElement
    const before = get.mock.calls.length
    await userEvent.click(within(row).getByRole('button', { name: 'Restore' }))
    await userEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Restore' }))
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(before))
  })
})

describe('copy action', () => {
  it('opens the create form prefilled, without the identifying attributes', async () => {
    await openEditor(userPath(1)) // an account without the POSIX part
    const source = must(db.get(userDn(1)))
    await userEvent.click(screen.getByRole('button', { name: 'Actions' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Copy' }))

    const sn = await screen.findByLabelText(/^Last name/)
    expect(sn).toHaveValue(String(source.tabs.main?.values.sn))
    expect(screen.getByLabelText(/^Login/)).toHaveValue('')
    expect(screen.getByLabelText(/^Email/)).toHaveValue('')
    expect(screen.getByText(/Copy of /)).toBeInTheDocument()

    const create = vi.spyOn(api, 'createObject')
    await userEvent.type(screen.getByLabelText(/^Login/), 'copy-of-it')
    await userEvent.type(screen.getByLabelText(/^Email/), 'copy-of-it@example.com')
    await userEvent.click(await screen.findByRole('button', { name: /^Create/ }))
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    const body = must(create.mock.calls[0])[1]
    expect(body.tabs.main?.values).toMatchObject({
      uid: 'copy-of-it',
      sn: source.tabs.main?.values.sn,
    })
  })

  it('is not offered to users who cannot create the type', async () => {
    server.use(
      http.get('/api/v2/types', () =>
        HttpResponse.json([
          { name: 'user', label: 'User', label_plural: 'Users', icon: 'user', category: 'directory', can_create: false },
        ]),
      ),
    )
    signIn()
    renderApp(userPath(0))
    await screen.findByLabelText(/^Last name/)
    await userEvent.click(screen.getByRole('button', { name: 'Actions' }))
    await screen.findByRole('menuitem', { name: /View raw LDIF/ })
    expect(screen.queryByRole('menuitem', { name: 'Copy' })).not.toBeInTheDocument()
  })
})

describe('raw LDIF', () => {
  it('shows the LDIF built by the server', async () => {
    server.use(
      http.get('/api/v2/objects/:type/:dn/ldif', () =>
        HttpResponse.text('dn: uid=server,dc=example,dc=com\nobjectClass: top\n'),
      ),
    )
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: 'Actions' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /View raw LDIF/ }))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(dialog).toHaveTextContent('dn: uid=server,dc=example,dc=com'))
  })

  it('falls back to the form values while the endpoint does not exist yet', async () => {
    server.use(
      http.get('/api/v2/objects/:type/:dn/ldif', () =>
        HttpResponse.json({ error: { code: 'not_found', message: 'nope' } }, { status: 404 }),
      ),
    )
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: 'Actions' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /View raw LDIF/ }))
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(dialog).toHaveTextContent(/objectClass: top/))
  })
})

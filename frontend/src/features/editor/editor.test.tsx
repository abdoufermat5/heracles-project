import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { api } from '@/api/endpoints'
import { server } from '@/mocks/server'
import { renderApp, signIn, userPath } from '@/test/utils'

async function openEditor(path = userPath(0)) {
  signIn()
  renderApp(path)
  await screen.findByRole('heading', { level: 1 })
  await screen.findByLabelText(/^Last name/ )
}

describe('object editor', () => {
  it('shows values read-only first, then enables fields after acquiring the lock', async () => {
    const lock = vi.spyOn(api, 'lockObject')
    await openEditor()
    expect(screen.getByLabelText(/^Last name/ )).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    await waitFor(() => expect(screen.getByLabelText(/^Last name/ )).toBeEnabled())
    expect(lock).toHaveBeenCalledTimes(1)
  })

  it('tracks dirty state and sends only the changed attributes', async () => {
    const patch = vi.spyOn(api, 'patchObject')
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    const sn = await screen.findByLabelText(/^Last name/ )
    await waitFor(() => expect(sn).toBeEnabled())
    expect(screen.queryByTestId('dirty-indicator')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Save/ })).toBeDisabled()

    await userEvent.clear(sn)
    await userEvent.type(sn, 'Changed')
    expect(await screen.findByTestId('dirty-indicator')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))

    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1))
    const body = patch.mock.calls[0]?.[2]
    expect(body).toEqual({ tabs: { main: { active: true, values: { sn: 'Changed' } } } })
    await waitFor(() => expect(screen.getByLabelText(/^Last name/ )).toBeDisabled())
  })

  it('honours field-level read-only rights from the acl block', async () => {
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    await waitFor(() => expect(screen.getByLabelText(/^Last name/ )).toBeEnabled())
    // uid is "r" in the acl, employee type too
    expect(screen.getByLabelText(/^Login/ )).toBeDisabled()
    expect(screen.getByLabelText(/^Employee type/ )).toBeDisabled()
  })

  it('offers no edit action when the user has read-only object rights', async () => {
    signIn('viewer')
    renderApp(userPath(0))
    await screen.findByLabelText(/^Last name/ )
    expect(screen.queryByRole('button', { name: /Edit/ })).not.toBeInTheDocument()
    expect(screen.getByLabelText(/^Last name/ )).toBeDisabled()
    // password is hidden by the acl ("")
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })

  it('maps server validation errors onto the matching fields', async () => {
    server.use(
      http.patch('/api/v2/objects/:type/:dn', () =>
        HttpResponse.json(
          { error: { code: 'validation', message: 'Invalid', fields: { 'main.sn': 'Rejected by server' } } },
          { status: 422 },
        ),
      ),
    )
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    const sn = await screen.findByLabelText(/^Last name/ )
    await waitFor(() => expect(sn).toBeEnabled())
    await userEvent.type(sn, 'x')
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))
    expect(await screen.findByText('Rejected by server')).toBeInTheDocument()
    expect(sn).toHaveAttribute('aria-invalid', 'true')
  })

  it('validates required fields on the client before calling the API', async () => {
    const patch = vi.spyOn(api, 'patchObject')
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    const sn = await screen.findByLabelText(/^Last name/ )
    await waitFor(() => expect(sn).toBeEnabled())
    await userEvent.clear(sn)
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))
    expect(await screen.findByText('This field is required')).toBeInTheDocument()
    expect(patch).not.toHaveBeenCalled()
  })

  it('shows the lock holder when the object is locked by someone else', async () => {
    await openEditor(userPath(1))
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    const dialog = await screen.findByRole('alertdialog')
    expect(dialog).toHaveTextContent('bob.admin')
    expect(screen.getByLabelText(/^Last name/ )).toBeDisabled()
  })

  it('lets an optional tab be activated and sends it in the patch', async () => {
    const patch = vi.spyOn(api, 'patchObject')
    // find a user without the posix tab (index not divisible by 3)
    await openEditor(userPath(1 + 3))
    await userEvent.click(screen.getByRole('tab', { name: /POSIX account/ }))
    const toggle = await screen.findByRole('switch', { name: 'Enable POSIX account' })
    expect(toggle).not.toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    await waitFor(() => expect(toggle).toBeEnabled())
    await userEvent.click(toggle)
    await userEvent.type(await screen.findByLabelText(/^User id/ ), '2000')
    await userEvent.type(screen.getByLabelText(/^Group id/ ), '2000')
    await userEvent.type(screen.getByLabelText(/^Home directory/ ), '/home/x')
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))
    await waitFor(() => expect(patch).toHaveBeenCalled())
    const posix = patch.mock.calls[0]?.[2].tabs.posix
    expect(posix?.active).toBe(true)
    expect(posix?.values).toMatchObject({ uidNumber: 2000, gidNumber: 2000, homeDirectory: '/home/x' })
  })
})

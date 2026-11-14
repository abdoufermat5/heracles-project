import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { api } from '@/api/endpoints'
import { server } from '@/mocks/server'
import { objectsApi } from '@/features/editor/api'
import { renderApp, signIn, userPath } from '@/test/utils'

async function openEditor(path = userPath(0)) {
  const url = path.includes('?') ? path : `${path}?view=generic`
  signIn()
  renderApp(url)
  await screen.findByRole('heading', { level: 1 })
  await screen.findByLabelText(/^Last name/ )
}

async function confirmReview() {
  const dialog = await screen.findByRole('dialog', { name: /Review changes/ })
  await userEvent.click(within(dialog).getByRole('button', { name: 'Save changes' }))
}

describe('object editor', () => {
  it('offers Undo after a save and restores the undo-point snapshot', async () => {
    // sonner captures the pointer on its toasts; jsdom lacks it
    HTMLElement.prototype.setPointerCapture = () => undefined
    const restore = vi.spyOn(objectsApi, 'restoreSnapshot')
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    const sn = await screen.findByLabelText(/^Last name/)
    await waitFor(() => expect(sn).toBeEnabled())
    await userEvent.type(sn, 'x')
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))
    await confirmReview()
    await userEvent.click(await screen.findByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(restore).toHaveBeenCalledTimes(1))
  })

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

    // The diff is shown first (technical name, old and new value); nothing is sent yet.
    const review = await screen.findByRole('dialog', { name: /Review changes/ })
    expect(within(review).getByText('sn')).toBeInTheDocument()
    expect(within(review).getByText('Changed')).toBeInTheDocument()
    expect(patch).not.toHaveBeenCalled()
    await confirmReview()

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
    renderApp(`${userPath(0)}?view=generic`)
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
    await confirmReview()
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
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    await waitFor(() => expect(screen.getByLabelText(/^Last name/)).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /Add capability/ }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /Unix/ }))
    await userEvent.type(await screen.findByLabelText(/^User id/ ), '2000')
    await userEvent.type(screen.getByLabelText(/^Group id/ ), '2000')
    await userEvent.type(screen.getByLabelText(/^Home directory/ ), '/home/x')
    await userEvent.click(screen.getByRole('button', { name: /Save/ }))
    await confirmReview()
    await waitFor(() => expect(patch).toHaveBeenCalled())
    const posix = patch.mock.calls[0]?.[2].tabs.posix
    expect(posix?.active).toBe(true)
    expect(posix?.values).toMatchObject({ uidNumber: 2000, gidNumber: 2000, homeDirectory: '/home/x' })
  })

  it('shows sticky save bar when dirty and discard resets changes', async () => {
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    const sn = await screen.findByLabelText(/^Last name/ )
    await waitFor(() => expect(sn).toBeEnabled())
    const originalValue = (sn as HTMLInputElement).value

    // Save bar not visible yet
    expect(screen.queryByTestId('dirty-indicator')).not.toBeInTheDocument()

    // Make change
    await userEvent.clear(sn)
    await userEvent.type(sn, 'Temporary')

    // Dirty bar appears
    const indicator = await screen.findByTestId('dirty-indicator')
    expect(indicator).toBeInTheDocument()
    expect(indicator).toHaveTextContent(/unsaved change/i)

    // Discard changes
    const discardBtn = screen.getByRole('button', { name: /Discard/i })
    await userEvent.click(discardBtn)

    // Reverts to original value and exits edit mode
    await waitFor(() => {
      expect(screen.queryByTestId('dirty-indicator')).not.toBeInTheDocument()
      expect(screen.getByLabelText(/^Last name/ )).toHaveValue(originalValue)
      expect(screen.getByLabelText(/^Last name/ )).toBeDisabled()
    })
  })

  it('opens review changes popover displaying old and new values', async () => {
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    const sn = await screen.findByLabelText(/^Last name/ )
    await waitFor(() => expect(sn).toBeEnabled())

    await userEvent.clear(sn)
    await userEvent.type(sn, 'BrandNewName')

    // Open Review changes popover
    const reviewBtn = await screen.findByRole('button', { name: /Review changes/i })
    await userEvent.click(reviewBtn)

    // Verify diff content
    expect(await screen.findByText('BrandNewName')).toBeInTheDocument()
    expect(screen.getAllByText('Last name').length).toBeGreaterThanOrEqual(2)
  })

  it('opens raw LDIF dialog from actions menu', async () => {
    await openEditor()
    const actionsBtn = screen.getByRole('button', { name: /Actions/i })
    await userEvent.click(actionsBtn)

    const ldifItem = await screen.findByRole('menuitem', { name: /View raw LDIF/i })
    await userEvent.click(ldifItem)

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toBeInTheDocument()
    expect(dialog).toHaveTextContent(/dn:/)
    expect(screen.getByRole('button', { name: /Copy LDIF/i })).toBeInTheDocument()
  })

  it('saves changes when Ctrl+S keyboard shortcut is pressed', async () => {
    const patch = vi.spyOn(api, 'patchObject')
    await openEditor()
    await userEvent.click(screen.getByRole('button', { name: /Edit/ }))
    const sn = await screen.findByLabelText(/^Last name/ )
    await waitFor(() => expect(sn).toBeEnabled())

    await userEvent.clear(sn)
    await userEvent.type(sn, 'ShortcutSaved')
    expect(await screen.findByTestId('dirty-indicator')).toBeInTheDocument()

    await userEvent.keyboard('{Control>}s{/Control}')
    await confirmReview()

    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1))
    const body = patch.mock.calls[0]?.[2]
    expect(body).toEqual({ tabs: { main: { active: true, values: { sn: 'ShortcutSaved' } } } })
  })
})

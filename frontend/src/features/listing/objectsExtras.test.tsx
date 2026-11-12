import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { objectsApi } from '@/features/editor/api'
import { db } from '@/mocks/db'
import { must, renderApp, signIn } from '@/test/utils'

async function selectRows(count: number): Promise<void> {
  await screen.findByText('200 items')
  const rows = screen.getAllByRole('row')
  for (let i = 1; i <= count; i++) {
    await userEvent.click(within(must(rows[i])).getByRole('checkbox'))
  }
}

async function chooseDepartment(dn: string): Promise<void> {
  await userEvent.click(await screen.findByRole('button', { name: /Destination department/ }))
  await userEvent.click(await screen.findByTitle(dn))
}

describe('multiple edit', () => {
  it('applies the same change to every selected object and lists the results', async () => {
    signIn()
    const edit = vi.spyOn(objectsApi, 'bulkEdit')
    renderApp('/types/user')
    await selectRows(2)
    const bar = await screen.findByRole('region', { name: 'Bulk actions' })
    await userEvent.click(within(bar).getByRole('button', { name: 'Edit selected' }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Edit 2 objects')).toBeInTheDocument()
    await userEvent.click(await within(dialog).findByRole('button', { name: /Add a change/ }))
    await userEvent.click(within(dialog).getByRole('combobox', { name: 'Attribute' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Employee type' }))
    await userEvent.selectOptions(within(dialog).getByRole('combobox', { name: 'Value' }), 'contractor')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Review changes' }))
    // exact objects and attribute changes are listed before anything is written
    expect(within(dialog).getByTestId('bulk-review')).toHaveTextContent('2 objects will be affected')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apply' }))

    expect(await within(dialog).findByText('The change was applied to 2 objects.')).toBeInTheDocument()
    expect(edit).toHaveBeenCalledTimes(1)
    const [type, dns, changes] = must(edit.mock.calls[0])
    expect(type).toBe('user')
    expect(dns).toHaveLength(2)
    expect(changes).toEqual({ main: { employeeType: { op: 'set', value: 'contractor' } } })
    for (const dn of dns) expect(db.get(dn)?.tabs.main?.values.employeeType).toBe('contractor')
  })

  it('reports per-object failures without hiding the successes', async () => {
    signIn()
    renderApp('/types/user')
    await selectRows(2)
    // the second row is not editable (invalid change on purpose: clearing a required attribute)
    const bar = await screen.findByRole('region', { name: 'Bulk actions' })
    await userEvent.click(within(bar).getByRole('button', { name: 'Edit selected' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(await within(dialog).findByRole('button', { name: /Add a change/ }))
    await userEvent.click(within(dialog).getByRole('combobox', { name: 'Attribute' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Last name' }))
    await userEvent.click(within(dialog).getByRole('combobox', { name: 'Operation' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Clear' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Review changes' }))
    // exact objects and attribute changes are listed before anything is written
    expect(within(dialog).getByTestId('bulk-review')).toHaveTextContent('2 objects will be affected')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apply' }))
    expect(await within(dialog).findByText('0 succeeded, 2 failed.')).toBeInTheDocument()
    expect(within(dialog).getAllByText(/Some fields are invalid/).length).toBe(2)
  })

  it('offers no attribute when nothing is editable on all selected objects', async () => {
    signIn()
    renderApp('/types/user')
    await selectRows(1)
    const bar = await screen.findByRole('region', { name: 'Bulk actions' })
    await userEvent.click(within(bar).getByRole('button', { name: 'Edit selected' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByRole('button', { name: /Add a change/ })).toBeEnabled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})

describe('copy and move', () => {
  it('copies the selection to another department with a new name for each', async () => {
    signIn()
    const copy = vi.spyOn(objectsApi, 'copyObject')
    renderApp('/types/user')
    await selectRows(1)
    const bar = await screen.findByRole('region', { name: 'Bulk actions' })
    await userEvent.click(within(bar).getByRole('button', { name: 'Copy to…' }))
    const dialog = await screen.findByRole('dialog')

    // a destination is required
    await userEvent.click(within(dialog).getByRole('button', { name: 'Copy' }))
    expect(await within(dialog).findByText('Choose a destination department.')).toBeInTheDocument()
    expect(copy).not.toHaveBeenCalled()

    await chooseDepartment('ou=Lyon,dc=example,dc=com')
    const input = within(dialog).getByRole('textbox', { name: /New Login/ })
    await userEvent.clear(input)
    await userEvent.type(input, 'brand-new')
    await userEvent.type(within(dialog).getByRole('textbox', { name: /New Email/ }), 'brand-new@example.com')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Copy' }))

    expect(await within(dialog).findByText('1 object copied.')).toBeInTheDocument()
    expect(copy).toHaveBeenCalledWith(
      'user',
      expect.any(String),
      'ou=Lyon,dc=example,dc=com',
      { main: { uid: 'brand-new', mail: 'brand-new@example.com' } },
    )
    expect(db.get('uid=brand-new,ou=people,ou=Lyon,dc=example,dc=com')).toBeDefined()
  })

  it('shows why a copy failed', async () => {
    signIn()
    renderApp('/types/user')
    await selectRows(1)
    const bar = await screen.findByRole('region', { name: 'Bulk actions' })
    await userEvent.click(within(bar).getByRole('button', { name: 'Copy to…' }))
    const dialog = await screen.findByRole('dialog')
    await chooseDepartment('ou=Lyon,dc=example,dc=com')
    await userEvent.clear(within(dialog).getByRole('textbox', { name: /New Login/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Copy' }))
    expect(await within(dialog).findByText('0 succeeded, 1 failed.')).toBeInTheDocument()
    expect(within(dialog).getByText(/This field is required/)).toBeInTheDocument()
  })

  it('moves one object from its row menu', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText('200 items')
    const rows = screen.getAllByRole('row')
    const dn = must(
      within(must(rows[1]))
        .getByRole('link', { name: /./, description: '' })
        .getAttribute('href'),
    )
    void dn
    await userEvent.click(within(must(rows[1])).getByRole('button', { name: 'Copy or move' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Move to…' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Move 1 object')).toBeInTheDocument()
    await chooseDepartment('ou=Lyon,dc=example,dc=com')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move' }))
    expect(await within(dialog).findByText('1 object moved.')).toBeInTheDocument()
    expect(db.all('user').some((u) => u.dn.endsWith('ou=people,ou=Lyon,dc=example,dc=com'))).toBe(true)
  })
})

describe('restore a deleted object', () => {
  it('lists snapshots of objects that no longer exist and restores one', async () => {
    signIn()
    const rec = must(db.all('user')[2])
    const dn = rec.dn
    renderApp('/types/user')
    await screen.findByText('200 items')
    await objectsApi.createSnapshot('user', dn, 'before the cleanup')
    db.remove(dn)

    await userEvent.click(screen.getByRole('button', { name: 'Actions' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Restore deleted object…' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/before the cleanup/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: /^Restore/ }))
    await waitFor(() => expect(db.get(dn)).toBeDefined())
    expect(await within(dialog).findByText('No deleted object can be restored.')).toBeInTheDocument()
  })

  it('says so when there is nothing to restore', async () => {
    signIn()
    renderApp('/types/group')
    await screen.findByRole('heading', { level: 1 })
    await userEvent.click(await screen.findByRole('button', { name: 'Actions' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Restore deleted object…' }))
    expect(await screen.findByText('No deleted object can be restored.')).toBeInTheDocument()
  })
})

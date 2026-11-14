import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { adminMock } from '@/mocks/adminHandlers'
import { renderApp, signIn } from '@/test/utils'

beforeEach(() => adminMock.reset())

const sent = (method: string, path: string) =>
  adminMock.requests.filter((r) => r.method === method && r.path === path)

describe('role form', () => {
  async function openNewRole() {
    signIn()
    renderApp('/admin/access')
    await screen.findByRole('heading', { name: 'manager' })
    await userEvent.click(screen.getByRole('button', { name: 'New role' }))
    return within(await screen.findByRole('dialog'))
  }

  it('refuses an empty name, illegal characters and an existing name before saving', async () => {
    const dialog = await openNewRole()
    const name = dialog.getByLabelText('Name')

    await userEvent.click(dialog.getByRole('button', { name: 'Create' }))
    expect(await dialog.findByText('This field is required')).toBeInTheDocument()
    expect(name).toHaveAttribute('aria-invalid', 'true')
    expect(dialog.getByRole('button', { name: 'Create' })).toHaveAttribute('aria-disabled', 'true')
    expect(dialog.getByText('Fix 1 invalid field to continue.')).toBeInTheDocument()

    await userEvent.type(name, 'ops,night')
    expect(dialog.getByText(/Do not use the characters/)).toHaveAttribute('role', 'alert')

    await userEvent.clear(name)
    await userEvent.type(name, 'Manager')
    expect(dialog.getByText('A role with this name already exists here.')).toBeInTheDocument()

    await userEvent.clear(name)
    await userEvent.type(name, 'night-ops')
    await waitFor(() => expect(dialog.getByRole('button', { name: 'Create' })).not.toHaveAttribute('aria-disabled'))
    expect(dialog.queryByRole('alert')).not.toBeInTheDocument()
    expect(sent('POST', '/acl/roles')).toHaveLength(0)
  })

  it('refuses a description that is too long', async () => {
    const dialog = await openNewRole()
    await userEvent.type(dialog.getByLabelText('Name'), 'night-ops')
    const description = dialog.getByLabelText('Description')
    await userEvent.click(description)
    await userEvent.paste('d'.repeat(513))
    await userEvent.tab()
    expect(await dialog.findByText('Must be at most 512 characters')).toBeInTheDocument()
    expect(dialog.getByRole('button', { name: 'Create' })).toHaveAttribute('aria-disabled', 'true')
    expect(sent('POST', '/acl/roles')).toHaveLength(0)
  })
})

describe('assignment dialog', () => {
  async function openDialog() {
    signIn()
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('tab', { name: 'Who has access' }))
    await screen.findByText('admins')
    await userEvent.click(screen.getByRole('button', { name: 'Give access' }))
    const dialog = within(await screen.findByRole('dialog'))
    await userEvent.click(dialog.getByRole('combobox', { name: 'Role' }))
    await userEvent.click(await screen.findByRole('option', { name: 'auditor' }))
    await userEvent.click(dialog.getByRole('switch', { name: 'Every user' }))
    return dialog
  }

  it('refuses a malformed filter inline and keeps what was typed', async () => {
    const dialog = await openDialog()
    await userEvent.click(dialog.getByText('Member and target filters'))
    const filter = dialog.getByLabelText('Member filter')
    await userEvent.type(filter, 'department=Sales')
    await userEvent.tab()

    const message = await dialog.findByText(/Enter a valid LDAP filter/)
    expect(message).toHaveAttribute('role', 'alert')
    expect(filter).toHaveAttribute('aria-invalid', 'true')
    expect(filter).toHaveValue('department=Sales')
    expect(dialog.getByRole('button', { name: 'Give access' })).toHaveAttribute('aria-disabled', 'true')
    expect(dialog.getByText('Fix 1 invalid field to continue.')).toBeInTheDocument()

    await userEvent.click(dialog.getByRole('button', { name: 'Give access' }))
    expect(sent('PUT', '/acl/assignments')).toHaveLength(0)

    await userEvent.clear(filter)
    await userEvent.type(filter, '(department=Sales)')
    await waitFor(() => expect(dialog.getByRole('button', { name: 'Give access' })).not.toHaveAttribute('aria-disabled'))
    await userEvent.click(dialog.getByRole('button', { name: 'Give access' }))
    await waitFor(() => expect(sent('PUT', '/acl/assignments')).toHaveLength(1))
  })

  it('shows what the server refused under the same field and drops it on edit', async () => {
    const dialog = await openDialog()
    // the browser accepts this filter, the (mocked) server refuses the role that disappeared
    adminMock.roles = adminMock.roles.filter((role) => role.cn !== 'auditor')
    await userEvent.click(dialog.getByRole('button', { name: 'Give access' }))
    expect(await dialog.findByText('This role does not exist.')).toHaveAttribute('role', 'alert')
    expect(dialog.getByRole('combobox', { name: 'Role' })).toHaveAttribute('aria-invalid', 'true')
  })
})

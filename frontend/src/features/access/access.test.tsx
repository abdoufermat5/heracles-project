import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import en from '@/locales/en'
import fr from '@/locales/fr'
import { setTechnicalDetails } from '@/lib/preferences'
import { rdnValue } from '@/lib/objects'
import { adminMock } from '@/mocks/adminHandlers'
import { BASE_DN } from '@/mocks/db'
import { renderApp, signIn, userDn } from '@/test/utils'

beforeEach(() => {
  adminMock.reset()
  setTechnicalDetails(false)
})

function lastRequest(method: string, path: string) {
  return [...adminMock.requests].reverse().find((r) => r.method === method && r.path === path)
}

function flatten(node: unknown, prefix = ''): [string, unknown][] {
  if (typeof node !== 'object' || node === null) return [[prefix, node]]
  return Object.entries(node).flatMap(([key, value]) =>
    flatten(value, prefix === '' ? key : `${prefix}.${key}`),
  )
}

describe('access locales', () => {
  const used = new Set<string>()
  for (const file of readdirSync(__dirname).filter(
    (name) => name.endsWith('.tsx') && !name.includes('.test.'),
  )) {
    const source = readFileSync(join(__dirname, file), 'utf8')
    for (const match of source.matchAll(/\bt\(\s*'([a-zA-Z_]+\.[A-Za-z0-9_.]+)'/g)) {
      used.add(match[1] ?? '')
    }
  }
  const lookup = (tree: unknown, key: string): unknown =>
    key
      .split('.')
      .reduce<unknown>(
        (node, part) => (node as Record<string, unknown> | undefined)?.[part],
        tree,
      )

  it('defines every static key used by the access screens', () => {
    const missing = [...used]
      .filter((key) => key.startsWith('accessUI.'))
      .filter(
        (key) => typeof lookup(en, key) !== 'string' || typeof lookup(fr, key) !== 'string',
      )
    expect(missing).toEqual([])
  })

  it('keeps every access string in English and French', () => {
    const english = new Map(flatten(en.accessUI))
    const french = new Map(flatten(fr.accessUI))
    expect([...french.keys()].sort()).toEqual([...english.keys()].sort())
    for (const [key, value] of english) {
      expect(typeof value).toBe('string')
      expect(typeof french.get(key)).toBe('string')
      expect(french.get(key)).not.toBe('')
    }
  })
})

describe('role library', () => {
  it('summarises roles and hides directory names until technical details are on', async () => {
    signIn()
    renderApp('/admin/access')
    expect(await screen.findByRole('heading', { name: 'manager' })).toBeInTheDocument()
    const manager = screen.getByRole('heading', { name: 'manager' }).closest('article') as HTMLElement
    expect(
      await within(manager).findByText('Can view, create, edit, delete and move User account'),
    ).toBeInTheDocument()
    expect(within(manager).getByText('Assignments: 1')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'helpdesk' })).toBeInTheDocument()
    expect(screen.queryByText(/cn=manager/)).not.toBeInTheDocument()

    act(() => setTechnicalDetails(true))
    expect(screen.getByText(`cn=manager,ou=aclroles,${BASE_DN}`)).toBeInTheDocument()
  })

  it('filters the role cards by name', async () => {
    signIn()
    renderApp('/admin/access')
    await screen.findByRole('heading', { name: 'manager' })
    const search = screen.getByRole('searchbox', { name: 'Search roles' })
    await userEvent.type(search, 'audit')
    expect(screen.getByRole('heading', { name: 'auditor' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'manager' })).not.toBeInTheDocument()
  })

  it('creates a role from the permission matrix', async () => {
    signIn()
    renderApp('/admin/access')
    await screen.findByRole('heading', { name: 'manager' })
    await userEvent.click(screen.getByRole('button', { name: 'New role' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('No rights yet.')).toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText('Name'), 'team-lead')
    await userEvent.click(
      await within(dialog).findByRole('checkbox', { name: 'User account — view' }),
    )
    expect(
      within(dialog).getByText('Can view User account'),
    ).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(lastRequest('POST', '/acl/roles')).toBeDefined())
    const body = lastRequest('POST', '/acl/roles')?.body as {
      cn: string
      templates: { blocks: { object: string; rights: string; attributes: unknown[] }[] }[]
    }
    expect(body.cn).toBe('team-lead')
    expect(body.templates[0]?.blocks).toEqual([
      { object: 'user/user', rights: 'r', attributes: [] },
    ])
    expect(await screen.findByRole('heading', { name: 'team-lead' })).toBeInTheDocument()
  })

  it('sends an untouched role back with its stored template', async () => {
    signIn()
    renderApp('/admin/access')
    await screen.findByRole('heading', { name: 'manager' })
    await userEvent.click(screen.getByRole('button', { name: 'Edit role manager' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(lastRequest('PUT', '/acl/roles')).toBeDefined())
    const body = lastRequest('PUT', '/acl/roles')?.body as { templates: { raw?: string }[] }
    expect(body.templates[0]?.raw).toBe('0:user/user;cmdrw,user/posixAccount;cmdrw')
  })

  it('duplicates a role and keeps its rights', async () => {
    signIn()
    renderApp('/admin/access')
    await screen.findByRole('heading', { name: 'manager' })
    await userEvent.click(screen.getByRole('button', { name: 'Duplicate role manager' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText('Name')).toHaveValue('manager (copy)')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(lastRequest('POST', '/acl/roles')).toBeDefined())
    const body = lastRequest('POST', '/acl/roles')?.body as {
      cn: string
      templates: { raw?: string }[]
    }
    expect(body.cn).toBe('manager (copy)')
    expect(body.templates[0]?.raw).toBe('0:user/user;cmdrw,user/posixAccount;cmdrw')
  })

  it('explains where a role is used before deleting it', async () => {
    signIn()
    renderApp('/admin/access')
    await screen.findByRole('heading', { name: 'manager' })
    await userEvent.click(screen.getByRole('button', { name: 'Delete role manager' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(
      within(dialog).getByText(/Deleting it takes these rights away from the people and groups below/),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('Top level')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete role' }))
    await waitFor(() => expect(lastRequest('DELETE', '/acl/roles')).toBeDefined())
    expect(adminMock.roles.map((role) => role.cn)).not.toContain('manager')
  })
})

describe('who has access', () => {
  it('lists people, groups and roles with their role, place and scope', async () => {
    signIn()
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('tab', { name: 'Who has access' }))
    const admins = (await screen.findByText('admins')).closest('li') as HTMLElement
    expect(within(admins).getByText('manager')).toBeInTheDocument()
    expect(within(admins).getByText('Subtree')).toBeInTheDocument()
    expect(within(admins).getByText('Top level')).toBeInTheDocument()
    expect(within(admins).getByText('group')).toBeInTheDocument()

    const staff = screen.getByText('staff').closest('li') as HTMLElement
    expect(within(staff).getByText('helpdesk')).toBeInTheDocument()
    expect(within(staff).getByText('Paris')).toBeInTheDocument()
    expect(screen.getByText('Every user')).toBeInTheDocument()
  })

  it('filters by role', async () => {
    signIn()
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('tab', { name: 'Who has access' }))
    await screen.findByText('admins')
    await userEvent.click(screen.getByRole('button', { name: 'Role' }))
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: /manager/ }))
    expect(screen.getByText('admins')).toBeInTheDocument()
    expect(screen.queryByText('Every user')).not.toBeInTheDocument()
  })

  it('gives a role to everyone on a department', async () => {
    signIn()
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('tab', { name: 'Who has access' }))
    await screen.findByText('admins')
    await userEvent.click(screen.getByRole('button', { name: 'Give access' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('combobox', { name: 'Role' }))
    await userEvent.click(await screen.findByRole('option', { name: 'auditor' }))
    await userEvent.click(within(dialog).getByRole('switch', { name: 'Every user' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Give access' }))
    await waitFor(() => expect(lastRequest('PUT', '/acl/assignments')).toBeDefined())
    const body = lastRequest('PUT', '/acl/assignments')?.body as {
      assignments: { role?: string; scope?: string; members: unknown[] }[]
    }
    const added = body.assignments.at(-1)
    expect(added).toMatchObject({ scope: 'subtree', members: ['*'] })
    expect(added?.role).toBe(`cn=auditor,ou=aclroles,${BASE_DN}`)
    expect(adminMock.assignments[BASE_DN]?.length).toBe(4)
  })

  it('removes one member from an assignment, keeping the others', async () => {
    signIn()
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('tab', { name: 'Who has access' }))
    await screen.findByText('admins')
    await userEvent.click(screen.getByRole('button', { name: 'Remove access for admins' }))
    const dialog = await screen.findByRole('alertdialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(lastRequest('PUT', '/acl/assignments')).toBeDefined())
    await waitFor(() =>
      expect(adminMock.assignments[BASE_DN]?.map((a) => a.role_name)).toEqual([
        'editownpwd',
        'auditor',
      ]),
    )
  })
})

describe('check rights', () => {
  async function choosePerson(): Promise<string> {
    const uid = rdnValue(userDn(0))
    await userEvent.click(screen.getByRole('combobox', { name: 'Person' }))
    const input = await screen.findByRole('textbox', { name: 'Search…' })
    await userEvent.type(input, uid)
    await userEvent.click(await screen.findByRole('option', { name: new RegExp(uid) }))
    return uid
  }

  it('answers yes and says which assignment grants the right', async () => {
    signIn()
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('tab', { name: 'Check rights' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Check' }))
    expect(screen.getByRole('button', { name: 'Check' })).toBeDisabled()
    const uid = await choosePerson()
    await userEvent.click(screen.getByRole('button', { name: 'Check' }))
    expect(await screen.findByText('Yes, this is allowed')).toBeInTheDocument()
    expect(
      await screen.findByText(new RegExp(`^${uid} can view User account in Example`)),
    ).toBeInTheDocument()
    expect(screen.getByText(/Because manager is assigned on/)).toBeInTheDocument()
    expect(lastRequest('POST', '/acl/check')).toBeDefined()
  })

  it('answers no when no assignment grants the action', async () => {
    signIn()
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('tab', { name: 'Check rights' }))
    await choosePerson()
    await userEvent.click(screen.getByRole('combobox', { name: 'Action' }))
    await userEvent.click(await screen.findByRole('option', { name: 'create' }))
    await userEvent.click(screen.getByRole('combobox', { name: 'Object type' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Group' }))
    await userEvent.click(screen.getByRole('button', { name: 'Check' }))
    expect(await screen.findByText('No, this is not allowed')).toBeInTheDocument()
    expect(screen.getByText('No assignment grants this right there.')).toBeInTheDocument()
  })
})

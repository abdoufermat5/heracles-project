import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import en from '@/locales/en'
import fr from '@/locales/fr'
import { adminMock } from '@/mocks/adminHandlers'
import { BASE_DN } from '@/mocks/db'
import { must, renderApp, signIn } from '@/test/utils'
import { server } from '@/mocks/server'
import { nextDraft, normalise } from './configModel'
import { toggleRight } from './rights'
import type { ConfigField } from './types'

beforeEach(() => adminMock.reset())

function lastRequest(method: string, path: string) {
  return [...adminMock.requests].reverse().find((r) => r.method === method && r.path === path)
}

describe('locales', () => {
  const dir = __dirname
  const used = new Set<string>()
  for (const file of readdirSync(dir).filter((f) => f.endsWith('.tsx') && !f.includes('.test.'))) {
    const source = readFileSync(join(dir, file), 'utf8')
    for (const m of source.matchAll(/\bt\(\s*'([a-z_]+\.[A-Za-z0-9_.]+)'/g)) used.add(m[1] ?? '')
  }

  const lookup = (tree: unknown, key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], tree)

  it('defines every key used by the administration screens in English and French', () => {
    const namespaces = ['admin', 'acl', 'config', 'hooks', 'setup', 'plugins', 'tasks']
    const missing = [...used]
      .filter((k) => namespaces.includes(k.split('.')[0] ?? ''))
      .filter((k) => typeof lookup(en, k) !== 'string' || typeof lookup(fr, k) !== 'string')
    expect(missing).toEqual([])
  })

  it('translates the dynamic keys: rights, member kinds, trigger modes and checks', () => {
    for (const letter of ['r', 'w', 'c', 'd', 'm', 't', 's']) {
      expect(typeof lookup(fr, `acl.right.${letter}`)).toBe('string')
    }
    for (const kind of ['user', 'group', 'role', 'everyone', 'missing'])
      expect(typeof lookup(fr, `acl.kind.${kind}`)).toBe('string')
    for (const id of ['root_object', 'super_admin', 'default_roles', 'users_tree', 'duplicate_ids'])
      expect(typeof lookup(fr, `setup.check.${id}`)).toBe('string')
    expect(fr.hooks.modes.premodify).not.toBe(en.hooks.modes.premodify)
  })
})

describe('config model', () => {
  const field: ConfigField = {
    key: 'password_min_length',
    section: 'password',
    kind: 'int',
    honoured: true,
    options: [],
    secret: false,
    default: 8,
    value: 8,
    source: 'default',
    hidden: false,
  }

  it('keeps only the values that differ from the stored ones', () => {
    const changed = nextDraft({}, field, 12)
    expect(changed).toEqual({ password_min_length: 12 })
    expect(nextDraft(changed, field, 8)).toEqual({})
  })

  it('treats empty and unset values alike', () => {
    expect(normalise({ kind: 'str' }, null)).toBe('')
    expect(normalise({ kind: 'bool' }, null)).toBe(false)
    expect(normalise({ kind: 'list' }, null)).toEqual([])
  })

  it('toggles rights in canonical order', () => {
    expect(toggleRight('rw', 'c')).toBe('rwc')
    expect(toggleRight('rwc', 'w')).toBe('rc')
    expect(toggleRight('rw', 's')).toBe('srw')
  })
})

describe('administration navigation', () => {
  it('shows the administration group with the entries the user may use', async () => {
    signIn()
    renderApp('/')
    const nav = await screen.findByTestId('admin-nav')
    for (const name of ['Access control', 'Configuration', 'Directory health', 'Plugins', 'Tasks'])
      expect(within(nav).getByRole('link', { name })).toBeInTheDocument()
  })

  it('hides the entries the user has no rights for', async () => {
    signIn('viewer')
    renderApp('/')
    const nav = await screen.findByTestId('admin-nav')
    expect(within(nav).getByRole('link', { name: 'Configuration' })).toBeInTheDocument()
    expect(within(nav).queryByRole('link', { name: 'Access control' })).not.toBeInTheDocument()
    expect(within(nav).queryByRole('link', { name: 'Tasks' })).not.toBeInTheDocument()
  })

  it('refuses a screen the user has no rights for', async () => {
    signIn('viewer')
    renderApp('/admin/access')
    expect(await screen.findByText('You do not have access to this section')).toBeInTheDocument()
  })
})

describe('configuration screen', () => {
  it('saves only the changed attributes', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Password' }))
    const input = await screen.findByLabelText('Minimum length')
    await userEvent.clear(input)
    await userEvent.type(input, '14')
    expect(await screen.findByText('Changes to save: 1')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(lastRequest('PUT', '/config')).toBeDefined())
    expect(lastRequest('PUT', '/config')?.body).toEqual({ changes: { password_min_length: 14 } })
    expect(await screen.findByText('No changes.')).toBeInTheDocument()
  })

  it('marks the settings that are only stored for compatibility', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Look & feel' }))
    const row = (await screen.findByText('Time zone')).closest('div.grid')
    expect(row).not.toBeNull()
    expect(within(row as HTMLElement).getByText('Stored for compatibility')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Password' }))
    const honoured = (await screen.findByText('Minimum length')).closest('div.grid')
    expect(within(honoured as HTMLElement).queryByText('Stored for compatibility')).toBeNull()
  })

  it('offers the login method and CAS settings in the login section', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Login & session' }))
    expect(await screen.findByLabelText('Login method')).toBeInTheDocument()
    expect(screen.getByLabelText('CAS host')).toBeInTheDocument()
    expect(screen.getByLabelText('Session lifetime (seconds)')).toBeInTheDocument()
  })

  it('shows server-side validation errors on the field', async () => {
    signIn()
    server.use(
      http.put('/api/v2/admin/config', () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation',
              message: 'Invalid configuration',
              fields: { password_min_length: 'Must not be negative.' },
            },
          },
          { status: 422 },
        ),
      ),
    )
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Password' }))
    const input = await screen.findByLabelText('Minimum length')
    await userEvent.clear(input)
    await userEvent.type(input, '5')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Must not be negative.')).toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'true')
  })

  it('is read-only without the right to write', async () => {
    signIn('viewer')
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Password' }))
    expect(await screen.findByLabelText('Minimum length')).toBeDisabled()
    expect(screen.getByText('You can view this configuration but not change it.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('hides secret values from users who cannot write', async () => {
    signIn('viewer')
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Password recovery' }))
    const salt = await screen.findByLabelText('Token salt')
    expect(salt).toHaveValue('')
    expect(salt).toHaveAttribute('placeholder', 'Hidden')
  })

  it('edits the triggers table and saves the list', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Triggers' }))
    expect(await screen.findByText('No triggers')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add trigger' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('combobox', { name: 'Tab' }))
    await userEvent.click(await screen.findByRole('option', { name: 'posixAccount' }))
    await userEvent.type(within(dialog).getByLabelText('Command'), '/usr/bin/provision %uid%')
    await userEvent.click(within(dialog).getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('/usr/bin/provision %uid%')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(lastRequest('PUT', '/hooks')).toBeDefined())
    expect(lastRequest('PUT', '/hooks')?.body).toMatchObject({
      hooks: [{ tab: 'posixAccount', mode: 'postcreate', command: '/usr/bin/provision %uid%', enabled: true }],
    })
    // toggle and delete
    await userEvent.click(await screen.findByRole('switch', { name: /Enable postcreate trigger on posixAccount/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(adminMock.hooks[0]?.enabled).toBe(false))
    await userEvent.click(screen.getByRole('button', { name: /Delete postcreate trigger on posixAccount/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(adminMock.hooks).toEqual([]))
  })
})

describe('directory health', () => {
  it('lists the checks with their status and offending entries', async () => {
    signIn()
    renderApp('/admin/health')
    const users = await screen.findByText('Users location')
    const card = users.closest('li') as HTMLElement
    expect(within(card).getByText('Warning')).toBeInTheDocument()
    expect(within(card).getByText(`uid=a,ou=misc,${BASE_DN}`)).toBeInTheDocument()
    const root = (await screen.findByText('Base entry')).closest('li') as HTMLElement
    expect(within(root).getByText('OK')).toBeInTheDocument()
    expect(screen.getByText('Errors: 1')).toBeInTheDocument()
  })

  it('applies a fix to the selected entries only, then re-runs', async () => {
    signIn()
    renderApp('/admin/health')
    const card = (await screen.findByText('Users location')).closest('li') as HTMLElement
    await userEvent.click(within(card).getByRole('checkbox', { name: `uid=b,ou=misc,${BASE_DN}` }))
    await userEvent.click(within(card).getByRole('button', { name: 'Fix 1 selected' }))
    await waitFor(() => expect(lastRequest('POST', '/checks/users_tree/fix')).toBeDefined())
    expect(lastRequest('POST', '/checks/users_tree/fix')?.body).toEqual({
      dns: [`uid=a,ou=misc,${BASE_DN}`],
      options: {},
    })
    await userEvent.click(screen.getByRole('button', { name: 'Run the checks again' }))
    await waitFor(() => expect(screen.getAllByText('OK').length).toBeGreaterThan(0))
  })

  it('needs a user before it can create a super administrator', async () => {
    signIn()
    renderApp('/admin/health')
    const card = (await screen.findByText('Super administrator')).closest('li') as HTMLElement
    expect(within(card).getByRole('button', { name: 'Make administrator' })).toBeDisabled()
    expect(within(card).getByRole('combobox', { name: 'User to promote' })).toBeInTheDocument()
  })

  it('does not offer a fix for report-only checks', async () => {
    signIn()
    renderApp('/admin/health')
    const card = (await screen.findByText('Duplicate identifiers')).closest('li') as HTMLElement
    expect(within(card).queryByRole('button')).toBeNull()
  })

  it('shows the results read-only without the right to write', async () => {
    signIn('viewer')
    renderApp('/admin/health')
    const card = (await screen.findByText('Default roles')).closest('li') as HTMLElement
    expect(within(card).getByRole('button', { name: /Fix 1 selected/ })).toBeDisabled()
    expect(screen.getByText('You can see the results but not apply fixes.')).toBeInTheDocument()
  })
})

describe('plugins page', () => {
  it('shows version, state, missing classes and contributions', async () => {
    signIn()
    renderApp('/admin/plugins')
    const posix = (await screen.findByText('posix')).closest('tr') as HTMLElement
    expect(within(posix).getByText('Enabled')).toBeInTheDocument()
    expect(within(posix).getByText('Unix group')).toBeInTheDocument()
    expect(within(posix).getByText('0.1.0')).toBeInTheDocument()
    const samba = (await screen.findByText('samba')).closest('tr') as HTMLElement
    expect(within(samba).getByText('Disabled')).toBeInTheDocument()
    expect(within(samba).getByText('sambaSamAccount')).toBeInTheDocument()
  })
})

describe('tasks dashboard', () => {
  it('lists the tasks with progress and filters them', async () => {
    signIn()
    renderApp('/admin/tasks')
    const row = (await screen.findByText('purge-audit')).closest('tr') as HTMLElement
    expect(within(row).getByText('Activated')).toBeInTheDocument()
    expect(within(row).getByText('3 of 4 done')).toBeInTheDocument()
    expect(within(row).getByText(/1 failed/)).toBeInTheDocument()
    expect(screen.getByText('old-reminder')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('combobox', { name: 'Status' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Deactivated' }))
    await waitFor(() => expect(screen.queryByText('purge-audit')).not.toBeInTheDocument())
    expect(screen.getByText('old-reminder')).toBeInTheDocument()
  })

  it('runs a task now and retries its failed sub-tasks', async () => {
    signIn()
    renderApp('/admin/tasks')
    const row = (await screen.findByText('purge-audit')).closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Run purge-audit now' }))
    await waitFor(() => expect(lastRequest('POST', '/tasks/run')).toBeDefined())
    await userEvent.click(within(row).getByRole('button', { name: 'Retry failed sub-tasks of purge-audit' }))
    await waitFor(() => expect(lastRequest('POST', '/tasks/retry')).toBeDefined())
    await waitFor(() =>
      expect(
        within(must(screen.getByText('purge-audit').closest('tr'))).getByRole('button', {
          name: 'Retry failed sub-tasks of purge-audit',
        }),
      ).toBeDisabled(),
    )
  })

  it('does not let the user run tasks they cannot write', async () => {
    signIn()
    renderApp('/admin/tasks')
    const row = (await screen.findByText('old-reminder')).closest('tr') as HTMLElement
    expect(within(row).getByRole('button', { name: 'Run old-reminder now' })).toBeDisabled()
  })
})

describe('access control', () => {
  it('lists the roles and how many assignments use them', async () => {
    signIn()
    renderApp('/admin/access')
    const row = (await screen.findByText('manager')).closest('tr') as HTMLElement
    expect(within(row).getByText('All rights on users')).toBeInTheDocument()
    expect(screen.getByText('editownpwd')).toBeInTheDocument()
  })

  it('creates a role from the rights matrix', async () => {
    signIn()
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('button', { name: 'New role' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Name'), 'auditor')
    await userEvent.click(within(dialog).getByRole('combobox', { name: 'Add object' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Users › User' }))
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /user\/user.*Write/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(lastRequest('POST', '/acl/roles')).toBeDefined())
    const body = lastRequest('POST', '/acl/roles')?.body as {
      cn: string
      templates: { blocks: { object: string; rights: string }[] }[]
    }
    expect(body.cn).toBe('auditor')
    expect(body.templates[0]?.blocks[0]).toMatchObject({ object: 'user/user', rights: 'rw' })
    expect(await screen.findByText('auditor')).toBeInTheDocument()
  })

  it('sends an unedited role back with its stored template', async () => {
    signIn()
    renderApp('/admin/access')
    await screen.findByText('manager')
    await userEvent.click(screen.getByRole('button', { name: 'Edit role manager' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(lastRequest('PUT', '/acl/roles')).toBeDefined())
    const body = lastRequest('PUT', '/acl/roles')?.body as { templates: { raw?: string }[] }
    expect(body.templates[0]?.raw).toBe('0:user/user;cmdrw,user/posixAccount;cmdrw')
  })

  it('asks for confirmation before deleting a role in use', async () => {
    signIn()
    renderApp('/admin/access')
    await screen.findByText('manager')
    await userEvent.click(screen.getByRole('button', { name: 'Delete role manager' }))
    expect(await screen.findByText(/used by 1 assignment/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(adminMock.roles.map((r) => r.cn)).toEqual(['editownpwd']))
  })

  it('reorders the assignments by changing their priorities', async () => {
    signIn()
    adminMock.assignments[BASE_DN] = [
      {
        raw: 'a',
        index: 0,
        scope: 'subtree',
        role: `cn=manager,ou=aclroles,${BASE_DN}`,
        role_name: 'manager',
        members: [{ dn: '*', kind: 'everyone' }],
      },
      {
        raw: 'b',
        index: 1,
        scope: 'base',
        role: `cn=editownpwd,ou=aclroles,${BASE_DN}`,
        role_name: 'editownpwd',
        members: [{ dn: '*', kind: 'everyone' }],
      },
    ]
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('tab', { name: 'Assignments' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Move manager down' }))
    await waitFor(() => expect(lastRequest('PUT', '/acl/assignments')).toBeDefined())
    const sent = lastRequest('PUT', '/acl/assignments')?.body as { assignments: { role: string; index: number }[] }
    expect(sent.assignments.map((a) => [a.role.split(',')[0], a.index])).toEqual([
      ['cn=editownpwd', 0],
      ['cn=manager', 1],
    ])
  })

  it('adds an assignment with a role and its members', async () => {
    signIn()
    adminMock.assignments = {}
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('tab', { name: 'Assignments' }))
    expect(await screen.findByText('No assignments here')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add assignment' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('combobox', { name: 'Role' }))
    await userEvent.click(await screen.findByRole('option', { name: 'manager' }))
    await userEvent.click(within(dialog).getByRole('switch', { name: 'Every user' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'OK' }))
    await waitFor(() => expect(lastRequest('PUT', '/acl/assignments')).toBeDefined())
    const sent = lastRequest('PUT', '/acl/assignments')?.body as {
      assignments: { role: string; scope: string; members: string[] }[]
    }
    expect(sent.assignments).toHaveLength(1)
    expect(sent.assignments[0]).toMatchObject({ scope: 'subtree', members: ['*'] })
    expect(sent.assignments[0]?.role).toContain('cn=manager')
    expect(await screen.findByText('Every user')).toBeInTheDocument()
  })

  it('keeps the rights check disabled until a user is chosen', async () => {
    signIn()
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('tab', { name: 'Check rights' }))
    await userEvent.type(await screen.findByLabelText('Distinguished name of the target object'), `uid=x,${BASE_DN}`)
    expect(screen.getByRole('button', { name: 'Check rights' })).toBeDisabled() // no user chosen yet
  })

  it('checks the effective rights of a user', async () => {
    signIn()
    renderApp('/admin/access')
    await userEvent.click(await screen.findByRole('tab', { name: 'Check rights' }))
    expect(await screen.findByText(/See the rights a user effectively has/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check rights' })).toBeDisabled()
  })
})

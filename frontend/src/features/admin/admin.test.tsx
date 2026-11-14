import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import { createElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { qk } from '@/api/hooks'
import i18n from '@/i18n'
import en from '@/locales/en'
import fr from '@/locales/fr'
import { adminMock } from '@/mocks/adminHandlers'
import { BASE_DN } from '@/mocks/db'
import { must, renderApp, signIn } from '@/test/utils'
import { server } from '@/mocks/server'
import { nextDraft, normalise } from './configModel'
import { useTogglePlugin } from './hooks'
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

  it('gives every health check a title, an explanation and a resolution in both languages', () => {
    // The server decides which checks exist; the four maps must cover each of them, or the
    // screen shows a raw key. The set is read from the explanation map, the one a new check
    // is written in first.
    const ids = Object.keys(en.settingsUI.health.checkExpl)
    expect(ids.length).toBeGreaterThan(0)
    for (const id of ids) {
      for (const tree of [en, fr]) {
        expect(typeof lookup(tree, `setup.check.${id}`)).toBe('string')
        expect(typeof lookup(tree, `settingsUI.health.checkExpl.${id}`)).toBe('string')
        expect(typeof lookup(tree, `settingsUI.health.checkFix.${id}`)).toBe('string')
      }
      expect(lookup(fr, `settingsUI.health.checkExpl.${id}`)).not.toBe(
        lookup(en, `settingsUI.health.checkExpl.${id}`),
      )
    }
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
  it('lists the administration entries the user may use', async () => {
    signIn()
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    for (const name of ['Configuration', 'Directory health', 'Plugins', 'Tasks', 'Access control'])
      expect(await within(nav).findByRole('link', { name })).toBeInTheDocument()
    // permissions live with the other access entries, tasks with the activity entries
    expect(
      within(within(nav).getByTestId('nav-group-access')).getByRole('link', {
        name: 'Access control',
      }),
    ).toBeInTheDocument()
    expect(
      within(within(nav).getByTestId('nav-group-activity')).getByRole('link', { name: 'Tasks' }),
    ).toBeInTheDocument()
  })

  it('hides the entries the user has no rights for', async () => {
    signIn('viewer')
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(await within(nav).findByRole('link', { name: 'Configuration' })).toBeInTheDocument()
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
    await userEvent.click(await screen.findByRole('button', { name: 'Passwords' }))
    const input = await screen.findByLabelText('Minimum length')
    await userEvent.clear(input)
    await userEvent.type(input, '14')
    expect(await screen.findByText('1 unsaved change')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(lastRequest('PUT', '/config')).toBeDefined())
    expect(lastRequest('PUT', '/config')?.body).toEqual({ changes: { password_min_length: 14 } })
    expect(await screen.findByText('No changes.')).toBeInTheDocument()
  })

  it('marks the settings that are only stored for compatibility', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Advanced' }))
    const row = (await screen.findByText('Time zone')).closest('div.grid')
    expect(row).not.toBeNull()
    expect(within(row as HTMLElement).getByText('Stored for compatibility')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Passwords' }))
    const honoured = (await screen.findByText('Minimum length')).closest('div.grid')
    expect(within(honoured as HTMLElement).queryByText('Stored for compatibility')).toBeNull()
  })

  it('offers the login method and CAS settings in the login section', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign-in & security' }))
    expect(await screen.findByLabelText('Login method')).toBeInTheDocument()
    expect(screen.getByLabelText('CAS host')).toBeInTheDocument()
    expect(screen.getByLabelText('Session lifetime (seconds)')).toBeInTheDocument()
  })

  it('filters settings across groups via the search box', async () => {
    signIn()
    renderApp('/admin/config')
    const search = await screen.findByPlaceholderText(/Search settings by name/)
    await userEvent.type(search, 'CAS host')
    expect(await screen.findByLabelText('CAS host')).toBeInTheDocument()
    expect(screen.queryByLabelText('Minimum length')).not.toBeInTheDocument()
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
    await userEvent.click(await screen.findByRole('button', { name: 'Passwords' }))
    const input = await screen.findByLabelText('Minimum length')
    await userEvent.clear(input)
    await userEvent.type(input, '5')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Must not be negative.')).toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'true')
  })

  it('is read-only without the right to write', async () => {
    signIn('viewer')
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Passwords' }))
    expect(await screen.findByLabelText('Minimum length')).toBeDisabled()
    expect(screen.getByText('Configuration is view-only for your account.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })

  it('hides secret values from users who cannot write', async () => {
    signIn('viewer')
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Notifications & mail' }))
    const salt = await screen.findByLabelText('Token salt')
    expect(salt).toHaveValue('')
    expect(salt).toHaveAttribute('placeholder', 'Hidden')
  })

  it('masks a secret value even for users who can write', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Notifications & mail' }))
    const salt = await screen.findByLabelText('Token salt')
    expect(salt).toHaveAttribute('type', 'password')
  })

  it('edits the triggers table and saves the list', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Automation & triggers' }))
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
    const posix = (await screen.findByText('posix')).closest('[data-plugin]') as HTMLElement
    expect(within(posix).getByText('Enabled')).toBeInTheDocument()
    expect(within(posix).getByText('POSIX group')).toBeInTheDocument()
    expect(within(posix).getByText('0.1.0')).toBeInTheDocument()
    const smb = (await screen.findByText('smb_accounts')).closest('[data-plugin]') as HTMLElement
    expect(within(smb).getByText('Unavailable')).toBeInTheDocument()
    expect(within(smb).getByText('sambaSamAccount')).toBeInTheDocument()
  })

  it('groups the cards as enabled, available and unavailable', async () => {
    signIn()
    renderApp('/admin/plugins')
    await screen.findByText('smb_accounts')
    const inGroup = (id: string) =>
      [...document.querySelectorAll(`[data-group="${id}"] [data-plugin]`)].map((n) =>
        n.getAttribute('data-plugin'),
      )
    expect(inGroup('enabled')).toEqual(['posix', 'acl_admin'])
    expect(inGroup('available')).toEqual(['dns'])
    expect(inGroup('unavailable')).toEqual(['smb_accounts'])
  })

  it('switches a plugin on', async () => {
    signIn()
    renderApp('/admin/plugins')
    const dns = (await screen.findByText('dns')).closest('[data-plugin]') as HTMLElement
    await userEvent.click(within(dns).getByRole('switch', { name: 'Enable plugin DNS' }))
    await waitFor(() => expect(lastRequest('PATCH', '/plugins/dns')?.body).toEqual({ enabled: true }))
    await waitFor(() =>
      expect(document.querySelector('[data-group="enabled"] [data-plugin="dns"]')).not.toBeNull(),
    )
  })

  it('rolls the switch back when the server refuses', async () => {
    signIn()
    adminMock.failPluginToggle = true
    renderApp('/admin/plugins')
    const dns = (await screen.findByText('dns')).closest('[data-plugin]') as HTMLElement
    await userEvent.click(within(dns).getByRole('switch', { name: 'Enable plugin DNS' }))
    await waitFor(() => expect(lastRequest('PATCH', '/plugins/dns')).toBeDefined())
    await waitFor(() =>
      expect(document.querySelector('[data-group="available"] [data-plugin="dns"]')).not.toBeNull(),
    )
  })

  it('disables the switch of an unavailable plugin and of the console plugin', async () => {
    signIn()
    renderApp('/admin/plugins')
    const smb = (await screen.findByText('smb_accounts')).closest('[data-plugin]') as HTMLElement
    expect(within(smb).getByRole('switch')).toBeDisabled()
    const own = (await screen.findByText('acl_admin')).closest('[data-plugin]') as HTMLElement
    expect(within(own).getByRole('switch')).toBeDisabled()
  })

  it('refreshes the types and the capabilities after a toggle', async () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    signIn()
    const { result } = renderHook(() => useTogglePlugin(), {
      wrapper: ({ children }) => createElement(QueryClientProvider, { client: qc }, children),
    })
    await result.current.mutateAsync({ name: 'dns', enabled: true })
    const keys = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey))
    expect(keys).toContain(JSON.stringify(qk.types))
    expect(keys).toContain(JSON.stringify(['admin', 'capabilities']))
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

  it('shows the last report, the recent runs and the scheduler notes', async () => {
    signIn()
    renderApp('/admin/tasks')
    const row = (await screen.findByText('purge-audit')).closest('tr') as HTMLElement
    expect(within(row).getByText(/events_purged 5/)).toBeInTheDocument()
    expect(within(screen.getByText('old-reminder').closest('tr') as HTMLElement).getByText('Not run by the scheduler yet')).toBeInTheDocument()
    const runs = await screen.findByRole('region', { name: 'Recent runs' })
    expect(within(runs).getByText('user_reminder')).toBeInTheDocument()
    expect(within(runs).getByText('Skipped')).toBeInTheDocument()
    expect(screen.getByText(/not forwarded to syslog/)).toBeInTheDocument()
  })

  it('offers a kind picker for new tasks', async () => {
    signIn()
    renderApp('/admin/tasks')
    await screen.findByText('purge-audit')
    const create = screen.getByRole('button', { name: 'New task' })
    expect(create).toBeDisabled()
    await userEvent.click(screen.getByRole('combobox', { name: 'Kind of task' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Reminder' }))
    expect(create).toBeEnabled()
  })

  it('does not let the user run tasks they cannot write', async () => {
    signIn()
    renderApp('/admin/tasks')
    const row = (await screen.findByText('old-reminder')).closest('tr') as HTMLElement
    expect(within(row).getByRole('button', { name: 'Run old-reminder now' })).toBeDisabled()
  })
})

describe('health results and run history', () => {
  const caps = {
    is_admin: true,
    console: true,
    acl: true,
    config: true,
    config_write: true,
    hooks: true,
    health: true,
    plugins: true,
    tasks: true,
    io: true,
  }

  afterEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('renders a health result in French with its interpolated parameters', async () => {
    signIn()
    await i18n.changeLanguage('fr')
    renderApp('/admin/health')

    expect(
      await screen.findByText(/2 utilisateur\(s\) sont hors de l'arborescence ou=people/),
    ).toBeInTheDocument()
    expect(screen.queryByText(/2 users are outside/)).not.toBeInTheDocument()
  })

  it('falls back to the English message when the key has no translation', async () => {
    server.use(
      http.get('/api/v2/admin/capabilities', () => HttpResponse.json(caps)),
      http.get('/api/v2/admin/checks', () =>
        HttpResponse.json([
          {
            id: 'root_object',
            status: 'ok',
            message: 'Fallback sentence.',
            message_key: 'root_object.unknown_outcome',
            message_params: {},
            dns: [],
            fixable: false,
            options: [],
          },
        ]),
      ),
    )
    signIn()
    await i18n.changeLanguage('fr')
    renderApp('/admin/health')

    expect(await screen.findByText('Fallback sentence.')).toBeInTheDocument()
    expect(screen.queryByText(/settingsUI\.health\.result/)).not.toBeInTheDocument()
    expect(screen.queryByText(/unknown_outcome/)).not.toBeInTheDocument()
  })

  it('shows why a run was skipped without an error count, and keeps the errors of a failed run', async () => {
    signIn()
    renderApp('/admin/tasks')

    const runs = await screen.findByRole('region', { name: 'Recent runs' })
    const skipped = (await within(runs).findByText('user_reminder')).closest('tr') as HTMLElement
    // translated from the stable id, not the English sentence the server sent
    expect(within(skipped).getByText(/No mail server is configured/)).toBeInTheDocument()
    expect(within(skipped).queryByText(/error\(s\)/)).not.toBeInTheDocument()

    const failed = (await within(runs).findByText('lifecycle')).closest('tr') as HTMLElement
    expect(within(failed).getByText('1 error(s)')).toBeInTheDocument()
    expect(within(failed).getByText('smtp refused the connection')).toBeInTheDocument()
  })
})

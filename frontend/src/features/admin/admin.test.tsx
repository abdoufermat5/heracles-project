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
import {
  effectiveValues,
  nextDraft,
  normalise,
  validateDraft,
  validateField,
} from './configModel'
import { useTogglePlugin } from './hooks'
import { checkHook, MAX_COMMAND_LENGTH } from './hookRules'
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
    constraints: { min: 1 },
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

  it('checks each setting against the constraints the server exposes', () => {
    const make = (over: Partial<ConfigField>): ConfigField => ({ ...field, constraints: {}, ...over })
    const rdn = make({ key: 'user_rdn', kind: 'str', constraints: { format: 'rdn' }, value: 'ou=people' })
    const port = make({ key: 'cas_port', kind: 'int', constraints: { min: 1, max: 65535 }, value: null })
    const hash = make({ key: 'password_default_hash', kind: 'select', options: ['ssha', 'argon2'], value: 'ssha' })
    const shells = make({
      key: 'shells',
      kind: 'list',
      constraints: { item_format: 'abs_path', unique: true },
      value: ['/bin/sh'],
    })
    const none = effectiveValues([rdn, port, hash, shells], {})
    expect(validateField(rdn, 'anything', none)).not.toBeNull()
    expect(validateField(rdn, 'ou=staff', none)).toBeNull()
    expect(validateField(rdn, '', none)).toBeNull()
    expect(validateField(port, 0, none)).toBe('Must be at least 1')
    expect(validateField(port, 70000, none)).toBe('Must be at most 65535')
    expect(validateField(port, 1.5, none)).toBe('Enter a whole number')
    expect(validateField(port, 389, none)).toBeNull()
    expect(validateField(hash, 'foo', none)).not.toBeNull()
    expect(validateField(hash, 'argon2', none)).toBeNull()
    expect(validateField(shells, ['/bin/sh', 'zsh'], none)).toContain('zsh')
    expect(validateField(shells, ['/bin/sh', '/bin/sh'], none)).toContain('/bin/sh')
  })

  it('reports a cross-field error on the key being written', () => {
    const make = (key: string, kind: ConfigField['kind'], value: ConfigField['value']): ConfigField => ({
      ...field,
      key,
      kind,
      value,
      constraints: {},
    })
    const fields = [
      make('shells', 'list', ['/bin/bash', '/bin/sh']),
      make('default_shell', 'str', '/bin/bash'),
      make('uid_number_base', 'str', '1100'),
      make('min_id', 'int', 1000),
      make('uid_pool_min', 'int', null),
      make('uid_pool_max', 'int', null),
    ]
    expect(Object.keys(validateDraft(fields, { shells: ['/bin/sh'] }))).toEqual(['shells'])
    expect(Object.keys(validateDraft(fields, { default_shell: '/bin/zsh' }))).toEqual(['default_shell'])
    expect(validateDraft(fields, { shells: ['/bin/sh'], default_shell: '/bin/sh' })).toEqual({})
    expect(Object.keys(validateDraft(fields, { uid_pool_min: 5, uid_pool_max: 2 }))).toEqual(['uid_pool_max'])
    expect(Object.keys(validateDraft(fields, { uid_number_base: '1100-1500', min_id: 2000 }))).toEqual([
      'uid_number_base',
    ])
    expect(Object.keys(validateDraft(fields, { min_id: 5000 }))).toEqual([])
    // emptying a list falls back to its default instead of failing
    expect(validateDraft(fields, { shells: [] })).toEqual({})
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
    // every administration tool lives in one collapsible block, apart from the object types
    const admin = await within(nav).findByTestId('nav-admin')
    await userEvent.click(within(admin).getByRole('button', { name: 'Administration' }))
    for (const name of ['Configuration', 'Directory health', 'Plugins', 'Tasks', 'Access control'])
      expect(await within(admin).findByRole('link', { name })).toBeInTheDocument()
    expect(
      within(within(nav).getByTestId('nav-directory')).queryByRole('link', { name: 'Tasks' }),
    ).not.toBeInTheDocument()
  })

  it('hides the entries the user has no rights for', async () => {
    signIn('viewer')
    renderApp('/')
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' })
    const admin = await within(nav).findByTestId('nav-admin')
    await userEvent.click(within(admin).getByRole('button', { name: 'Administration' }))
    expect(await within(admin).findByRole('link', { name: 'Configuration' })).toBeInTheDocument()
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

  it('marks a stored-only setting outside Advanced, not an honoured one', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign-in & security' }))
    const stored = (await screen.findByText('CAS host')).closest('div.grid')
    expect(within(stored as HTMLElement).getByText('Stored for compatibility')).toBeInTheDocument()
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

  it('refuses an invalid value inline and blocks saving until it is fixed', async () => {
    signIn()
    renderApp('/admin/config')
    const rdn = await screen.findByLabelText('Users container')
    await userEvent.clear(rdn)
    await userEvent.type(rdn, 'anything')
    // the message shows once the field has been left
    expect(screen.queryByText('Enter one RDN, such as ou=people')).not.toBeInTheDocument()
    await userEvent.tab()
    expect(await screen.findByText('Enter one RDN, such as ou=people')).toBeInTheDocument()
    expect(rdn).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
    expect(screen.getByText('1 setting needs fixing')).toBeInTheDocument()
    // the navigation counts the invalid settings of the group
    expect(screen.getByRole('button', { name: /General/ })).toHaveTextContent('1')
    expect(screen.getAllByLabelText('1 setting needs fixing').length).toBeGreaterThan(0)
    await userEvent.clear(rdn)
    await userEvent.type(rdn, 'ou=staff')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled())
    expect(screen.queryByText('Enter one RDN, such as ou=people')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(lastRequest('PUT', '/config')).toBeDefined())
    expect(lastRequest('PUT', '/config')?.body).toEqual({ changes: { user_rdn: 'ou=staff' } })
  })

  it('checks numbers against their bounds and keeps what was typed', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign-in & security' }))
    const port = await screen.findByLabelText('CAS port')
    expect(port).toHaveAttribute('min', '1')
    expect(port).toHaveAttribute('max', '65535')
    await userEvent.type(port, '0')
    await userEvent.tab()
    expect(await screen.findByText('Must be at least 1')).toBeInTheDocument()
    expect(port).toHaveValue(0)
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })

  it('offers the supported hash methods as choices and ties the default to the allowed ones', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Passwords' }))
    const group = await screen.findByRole('group', { name: 'Allowed hash methods' })
    await userEvent.click(within(group).getByRole('checkbox', { name: 'argon2' }))
    // the default (ssha) is not among the allowed hashes: the list is at fault
    expect(await screen.findByText('Must include the default hash (ssha).')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
    await userEvent.click(within(group).getByRole('checkbox', { name: 'ssha' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(lastRequest('PUT', '/config')).toBeDefined())
    expect(lastRequest('PUT', '/config')?.body).toEqual({
      changes: { password_allowed_hashes: ['ssha', 'argon2'] },
    })
  })

  it('shows the server refusal on the field, switches to its group and focuses it', async () => {
    signIn()
    server.use(
      http.put('/api/v2/admin/config', () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation',
              message: 'Invalid configuration',
              fields: { password_min_length: 'Must be at least 1.' },
            },
          },
          { status: 422 },
        ),
      ),
    )
    renderApp('/admin/config')
    const rdn = await screen.findByLabelText('Users container')
    await userEvent.clear(rdn)
    await userEvent.type(rdn, 'ou=x')
    await userEvent.click(screen.getByRole('button', { name: 'Passwords' }))
    const length = await screen.findByLabelText('Minimum length')
    await userEvent.clear(length)
    await userEvent.type(length, '5')
    await userEvent.click(screen.getByRole('button', { name: /^General/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Must be at least 1.')).toBeInTheDocument()
    expect(screen.getByLabelText('Minimum length')).toHaveFocus()
    expect(screen.getByLabelText('Minimum length')).toHaveValue(5)
  })

  it('renders and edits settings from a server that sends no constraints', async () => {
    signIn()
    server.use(
      http.get('/api/v2/admin/config', () =>
        HttpResponse.json({
          exists: true,
          can_write: true,
          sections: ['password'],
          fields: [
            {
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
            },
          ],
        }),
      ),
    )
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Passwords' }))
    const input = await screen.findByLabelText('Minimum length')
    expect(input).toHaveAttribute('min', '0')
    await userEvent.clear(input)
    await userEvent.type(input, '3')
    await userEvent.tab()
    expect(input).not.toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled()
  })

  it('says once, at the top of Advanced, that those settings are only stored', async () => {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Advanced' }))
    expect(await screen.findAllByText(/stores them but does not act on them/)).toHaveLength(1)
    expect(screen.queryByText('Stored for compatibility')).not.toBeInTheDocument()
    // the legacy sections are subheadings, not filters
    expect(screen.getByRole('heading', { name: 'Look & feel' })).toBeInTheDocument()
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

describe('trigger form validation', () => {
  async function openDialog() {
    signIn()
    renderApp('/admin/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Automation & triggers' }))
    await screen.findByText('No triggers')
    await userEvent.click(screen.getByRole('button', { name: 'Add trigger' }))
    return await screen.findByRole('dialog')
  }

  async function pickTab(dialog: HTMLElement, name: string) {
    await userEvent.click(within(dialog).getByRole('combobox', { name: 'Tab' }))
    await userEvent.click(await screen.findByRole('option', { name }))
  }

  it('refuses an empty tab and a command starting with # inline, and keeps the dialog open', async () => {
    const dialog = await openDialog()
    await userEvent.type(within(dialog).getByLabelText('Command'), '# not active')
    await userEvent.click(within(dialog).getByRole('button', { name: 'OK' }))
    expect(await within(dialog).findByText('Choose a tab.')).toBeInTheDocument()
    expect(
      within(dialog).getByText('A command cannot start with “#”: turn the trigger off instead.'),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('Fields to fix: 2.')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Command')).toHaveAttribute('aria-invalid', 'true')
    expect(within(dialog).getByRole('combobox', { name: 'Tab' })).toHaveAttribute('aria-invalid', 'true')
    // the typed command is kept and nothing reached the list or the server
    expect(within(dialog).getByLabelText('Command')).toHaveValue('# not active')
    expect(lastRequest('PUT', '/hooks')).toBeUndefined()
  })

  it('refuses a trigger that already exists', async () => {
    const dialog = await openDialog()
    await pickTab(dialog, 'posixAccount')
    const command = within(dialog).getByLabelText('Command')
    await userEvent.type(command, 'echo %uid%')
    await userEvent.click(within(dialog).getByRole('button', { name: 'OK' }))
    expect(await screen.findByText('echo %uid%')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Add trigger' }))
    const again = await screen.findByRole('dialog')
    await pickTab(again, 'posixAccount')
    await userEvent.type(within(again).getByLabelText('Command'), 'echo %uid%')
    await userEvent.click(within(again).getByRole('button', { name: 'OK' }))
    expect(await within(again).findByText('This trigger already exists.')).toBeInTheDocument()
  })

  it('checkHook mirrors the server rules (line break, NUL, length, unknown tab or event)', () => {
    const base = { tab: 'user', mode: 'check', command: 'true', enabled: true }
    const check = (patch: Partial<typeof base>) =>
      checkHook({ ...base, ...patch }, [], ['user'], ['check', 'postcreate'])
    expect(check({})).toEqual({})
    expect(check({ command: 'echo a\necho b' }).command).toBe('The command must fit on one line.')
    expect(check({ command: 'echo \0' }).command).toBe('The command must fit on one line.')
    expect(check({ command: 'x'.repeat(MAX_COMMAND_LENGTH + 1) }).command).toMatch(/at most 1000/i)
    expect(check({ command: 'x'.repeat(MAX_COMMAND_LENGTH) })).toEqual({})
    expect(check({ command: 'echo # fine' })).toEqual({})
    expect(check({ tab: 'nowhere' }).tab).toBe('This tab does not exist.')
    expect(check({ tab: 'a|b' }).tab).toBe('This tab does not exist.')
    expect(check({ mode: 'whenever' }).mode).toBe('Choose an event.')
  })

  it('shows what the server refused on the trigger row and keeps the typed values', async () => {
    server.use(
      http.put('/api/v2/admin/hooks', () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation',
              message: 'Invalid triggers',
              fields: { 'hooks.0.command': 'Same trigger as #1.' },
            },
          },
          { status: 422 },
        ),
      ),
    )
    const dialog = await openDialog()
    await pickTab(dialog, 'user')
    await userEvent.type(within(dialog).getByLabelText('Command'), 'true')
    await userEvent.click(within(dialog).getByRole('button', { name: 'OK' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Same trigger as #1.')).toBeInTheDocument()
    expect(screen.getByText('true')).toBeInTheDocument()
  })
})

describe('health fix validation', () => {
  it('blocks a fix with no entry selected and says why', async () => {
    signIn()
    renderApp('/admin/health')
    const card = (await screen.findByText('Users location')).closest('li') as HTMLElement
    await userEvent.click(within(card).getByRole('checkbox', { name: `uid=a,ou=misc,${BASE_DN}` }))
    await userEvent.click(within(card).getByRole('checkbox', { name: `uid=b,ou=misc,${BASE_DN}` }))
    expect(within(card).getByText('Select at least one entry to fix.')).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Fix 0 selected' })).toBeDisabled()
  })

  it('asks for a user before the promote button works, and says why', async () => {
    signIn()
    renderApp('/admin/health')
    const card = (await screen.findByText('Super administrator')).closest('li') as HTMLElement
    expect(within(card).getByText('Choose a user to enable this button.')).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Make administrator' })).toBeDisabled()
  })

  it('shows an entry the server refused next to that entry, not only in a toast', async () => {
    server.use(
      http.post('/api/v2/admin/checks/:id/fix', () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation',
              message: 'Invalid fix options',
              fields: { 'dns.0': 'This check does not report this entry.' },
            },
          },
          { status: 422 },
        ),
      ),
    )
    signIn()
    renderApp('/admin/health')
    const card = (await screen.findByText('Users location')).closest('li') as HTMLElement
    await userEvent.click(within(card).getByRole('button', { name: 'Fix 2 selected' }))
    const refused = await within(card).findByText(
      'The check no longer reports this entry. Run the checks again.',
    )
    expect(refused.closest('li')).toHaveTextContent(`uid=a,ou=misc,${BASE_DN}`)
    expect(within(card).getByRole('checkbox', { name: `uid=a,ou=misc,${BASE_DN}` })).toBeChecked()
  })
})

describe('task filter validation', () => {
  it('shows a filter the server refuses on its own control and lets the user clear it', async () => {
    server.use(
      http.get('/api/v2/admin/tasks', ({ request }) => {
        if (new URL(request.url).searchParams.get('status') !== 'Deactivated') return undefined
        return HttpResponse.json(
          {
            error: {
              code: 'validation',
              message: 'Unknown task status',
              fields: { status: 'Unknown task status.' },
            },
          },
          { status: 422 },
        )
      }),
    )
    signIn()
    renderApp('/admin/tasks')
    await screen.findByText('purge-audit')
    await userEvent.click(screen.getByRole('combobox', { name: 'Status' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Deactivated' }))
    expect(
      await screen.findByText('This status is not used by any task. Pick another status or clear the filter.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveAttribute('aria-invalid', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(await screen.findByText('purge-audit')).toBeInTheDocument()
  })
})

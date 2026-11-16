import { expect, request, test, type APIRequestContext } from '@playwright/test'
import { ADMIN, signIn, unique } from './helpers'

const BASE = 'dc=heracles,dc=test'

async function adminApi(baseURL: string): Promise<{ api: APIRequestContext; csrf: () => Promise<string> }> {
  const api = await request.newContext({ baseURL })
  const csrf = async () => ((await (await api.get('/api/v2/auth/csrf')).json()) as { token: string }).token
  const r = await api.post('/api/v2/auth/login', {
    data: { directory: 'main', username: ADMIN.login, password: ADMIN.password },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(r.ok()).toBeTruthy()
  return { api, csrf }
}

type Assignment = Record<string, unknown>

test('a service account gets API tokens that act with its own role only', async ({ page, baseURL }) => {
  const url = baseURL ?? 'http://localhost:8420'
  const { api, csrf } = await adminApi(url)
  const write = async (method: 'post' | 'put' | 'delete', path: string, data?: unknown) =>
    api[method](`/api/v2${path}`, { data, headers: { 'X-CSRF-Token': await csrf() } })
  const base = encodeURIComponent(BASE)

  // a service account, and a role reading users that names it in an ACL assignment
  const cn = unique('e2e-agent')
  const created = await write('post', '/objects/dsa', {
    base: '',
    tabs: { main: { values: { cn, userPassword: 'Agent-secret-1' } } },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const account = ((await created.json()) as { dn: string }).dn
  const role = await write('post', '/admin/acl/roles', {
    base: BASE,
    cn: unique('e2e-readers'),
    description: 'Reads users',
    templates: [{ index: 0, blocks: [{ object: 'user/user', rights: 'r', attributes: [] }] }],
  })
  expect(role.ok(), await role.text()).toBeTruthy()
  const roleDn = ((await role.json()) as { dn: string }).dn
  const before = ((await (await api.get(`/api/v2/admin/acl/assignments/${base}`)).json()) as {
    assignments: Assignment[]
  }).assignments
  const granted = await write('put', `/admin/acl/assignments/${base}`, {
    assignments: [...before, { index: before.length, scope: 'subtree', role: roleDn, members: [account] }],
  })
  expect(granted.ok(), await granted.text()).toBeTruthy()

  const bot = await request.newContext({ baseURL: url })
  try {
    await signIn(page, ADMIN.login, ADMIN.password)
    await expect(page).not.toHaveURL(/\/login/)
    await page.goto(`/types/dsa/${encodeURIComponent(account)}`)
    await page.getByRole('tab', { name: 'API tokens' }).click()
    await expect(page.getByText(/act with its rights only/)).toBeVisible()

    const mint = async (name: string, networks: string): Promise<string> => {
      await page.getByRole('button', { name: 'New token' }).click()
      const dialog = page.getByRole('dialog')
      await dialog.getByLabel('Name').fill(name)
      await dialog.getByLabel('Allowed addresses').fill(networks)
      await dialog.getByRole('button', { name: 'Create token' }).click()
      const secret = ((await dialog.locator('code').filter({ hasText: /^hrc_/ }).textContent()) ?? '').trim()
      await dialog.getByRole('button', { name: 'Done' }).click()
      return secret
    }

    // a bad network is reported in the dialog
    await page.getByRole('button', { name: 'New token' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Name').fill('bad')
    await dialog.getByLabel('Allowed addresses').fill('nope')
    await dialog.getByRole('button', { name: 'Create token' }).click()
    await expect(dialog.getByText('Not an address or a network: nope')).toBeVisible()
    await dialog.getByRole('button', { name: 'Cancel' }).click()

    // limited to a documentation network: refused from here
    const fenced = await mint('fenced', '203.0.113.0/24')
    await expect(page.getByText(/from 203\.0\.113\.0\/24/)).toBeVisible()
    await expect(page.getByText(new RegExp(`made by uid=${ADMIN.login},`)).first()).toBeVisible()
    const refused = await bot.get('/api/v2/auth/me', { headers: { Authorization: `Bearer ${fenced}` } })
    expect(refused.status()).toBe(403)
    expect(((await refused.json()) as { error: { code: string } }).error.code).toBe('token_ip')

    // unrestricted: reads users through the account's role, no groups
    const open = await mint('nightly', '')
    const auth = { Authorization: `Bearer ${open}` }
    const users = await bot.get('/api/v2/objects/user', { params: { scope: 'sub' }, headers: auth })
    expect(users.ok(), await users.text()).toBeTruthy()
    expect(((await users.json()) as { items: unknown[] }).items.length).toBeGreaterThan(0)
    const groups = await bot.get('/api/v2/objects/group', { params: { scope: 'sub' }, headers: auth })
    expect(((await groups.json()) as { items: unknown[] }).items).toEqual([])

    // revoked from the console: refused at once
    await page.getByRole('button', { name: 'Revoke nightly' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: /Revoke/ }).click()
    await expect(page.getByText('nightly', { exact: true })).toHaveCount(0)
    expect((await bot.get('/api/v2/auth/me', { headers: auth })).status()).toBe(401)
  } finally {
    await write('put', `/admin/acl/assignments/${base}`, { assignments: before })
    await write('delete', `/admin/acl/roles/${encodeURIComponent(roleDn)}`)
    await write('delete', `/objects/dsa/${encodeURIComponent(account)}`)
    await bot.dispose()
    await api.dispose()
  }
})

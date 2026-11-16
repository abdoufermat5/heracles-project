import { expect, request, test, type APIRequestContext, type Page } from '@playwright/test'
import { ADMIN, EMPLOYEE, signIn, signOut } from './helpers'

// The test identity provider of the `oidc` compose profile (deploy/e2e/oidc-realm.json).
const DISCOVERY = 'http://127.0.0.1:8180/realms/heracles/.well-known/openid-configuration'
const PERSON = { login: 'alice', password: 'alice-at-the-idp', name: 'Alice Martin' }
// Member of heracles-readers at the provider; `api.oidc.role_mapping` (deploy/e2e/heracles.yaml)
// maps that group to READERS.
const READER = { login: 'bob', password: 'bob-at-the-idp' }
const BASE = 'dc=heracles,dc=test'
const READERS = `cn=e2e-oidc-readers,ou=roles,${BASE}`
const PEOPLE = `ou=people,${BASE}`
const READ_PEOPLE = `cn=e2e-oidc-read-people,ou=aclroles,${BASE}`
const CAROL = `uid=carol,${PEOPLE}`

test.beforeAll(async ({ request }) => {
  const up = await request.get(DISCOVERY, { timeout: 3000 }).then(
    (r) => r.ok(),
    () => false,
  )
  test.skip(!up, 'no OpenID Connect provider (start the stack with --profile oidc)')
})

test('signs in through the OpenID Connect provider and out of both', async ({ page }) => {
  await page.goto('/login?redirect=%2Fme')
  // the password form stays next to the provider's button
  await expect(page.locator('#username')).toBeVisible()
  await page.getByRole('link', { name: 'Sign in with the test provider' }).click()

  // the provider's own sign-in page
  await expect(page).toHaveURL(/idp\.localhost:8180\/realms\/heracles\//)
  await page.locator('#username').fill(PERSON.login)
  await page.locator('#password').fill(PERSON.password)
  await page.locator('#kc-login').click()

  // back in the console, signed in as the directory entry the claim names
  await expect(page).toHaveURL(/localhost:8420\/me|127\.0\.0\.1:8431\/me/)
  await expect(page.getByText(PERSON.name).first()).toBeVisible()

  // signing out ends the provider's session too: the next attempt asks for the password again
  await signOut(page)
  await page.getByRole('link', { name: 'Sign in with the test provider' }).click()
  await expect(page.locator('#password')).toBeVisible()
  await expect(page).toHaveURL(/idp\.localhost:8180/)
})

test('a failed provider sign-in comes back to the form with an explanation', async ({ page }) => {
  await page.goto('/api/v2/auth/oidc/callback?code=forged&state=forged')
  await expect(page).toHaveURL(/\/login\?sso_error=/)
  await expect(page.getByRole('alert')).toContainText('Single sign-on failed')
  await expect(page.locator('#username')).toBeVisible()
})

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

async function readsCarol(page: Page): Promise<number> {
  return (await page.request.get(`/api/v2/objects/user/${encodeURIComponent(CAROL)}`)).status()
}

test('a group at the provider grants a directory role for the session only', async ({ page, baseURL }) => {
  const { api, csrf } = await adminApi(baseURL ?? 'http://localhost:8420')
  // the mapped role (nobody occupies it in the directory) and what it may do: read people
  // leftovers of an interrupted run on a kept stack
  await api.put(`/api/v2/admin/acl/assignments/${encodeURIComponent(PEOPLE)}`, {
    data: { assignments: [] },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  await api.delete(`/api/v2/admin/acl/roles/${encodeURIComponent(READ_PEOPLE)}`, { headers: { 'X-CSRF-Token': await csrf() } })
  await api.delete(`/api/v2/objects/role/${encodeURIComponent(READERS)}`, { headers: { 'X-CSRF-Token': await csrf() } })
  const role = await api.post('/api/v2/objects/role', {
    data: { base: '', tabs: { main: { values: { cn: 'e2e-oidc-readers' } } } },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(role.ok(), await role.text()).toBeTruthy()
  expect(((await role.json()) as { dn: string }).dn.toLowerCase()).toBe(READERS)
  const aclRole = await api.post('/api/v2/admin/acl/roles', {
    data: {
      cn: 'e2e-oidc-read-people',
      description: 'Created by the browser tests',
      templates: [{ index: 0, blocks: [{ object: 'user/user', rights: 'r', attributes: [] }] }],
    },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(aclRole.ok(), await aclRole.text()).toBeTruthy()
  const aclRoleDn = ((await aclRole.json()) as { dn: string }).dn
  const assigned = await api.put(`/api/v2/admin/acl/assignments/${encodeURIComponent(PEOPLE)}`, {
    data: { assignments: [{ index: 0, scope: 'subtree', role: aclRoleDn, members: [{ dn: READERS, kind: 'role' }] }] },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(assigned.ok(), await assigned.text()).toBeTruthy()

  try {
    // with the password, bob is a self-service user: carol's entry is out of reach
    await signIn(page, EMPLOYEE.login, EMPLOYEE.password)
    await expect(page).not.toHaveURL(/\/login/)
    expect(await readsCarol(page)).not.toBe(200)
    await signOut(page)

    // through the provider, bob's group gives him the role for this session
    await page.getByRole('link', { name: 'Sign in with the test provider' }).click()
    await expect(page).toHaveURL(/idp\.localhost:8180\/realms\/heracles\//)
    await page.locator('#username').fill(READER.login)
    await page.locator('#password').fill(READER.password)
    await page.locator('#kc-login').click()
    await expect(page).not.toHaveURL(/idp\.localhost|\/login/)
    expect(await readsCarol(page)).toBe(200)

    // the role was held by the session: the directory entry is unchanged
    const held = (await (await api.get(`/api/v2/objects/role/${encodeURIComponent(READERS)}`)).json()) as {
      tabs: { main: { values: Record<string, unknown> } }
    }
    expect(held.tabs.main.values.roleOccupant ?? []).toEqual([])
    await signOut(page)
  } finally {
    await api.put(`/api/v2/admin/acl/assignments/${encodeURIComponent(PEOPLE)}`, {
      data: { assignments: [] },
      headers: { 'X-CSRF-Token': await csrf() },
    })
    await api.delete(`/api/v2/admin/acl/roles/${encodeURIComponent(aclRoleDn)}`, { headers: { 'X-CSRF-Token': await csrf() } })
    await api.delete(`/api/v2/objects/role/${encodeURIComponent(READERS)}`, { headers: { 'X-CSRF-Token': await csrf() } })
    await api.dispose()
  }
})

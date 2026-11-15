import { expect, request, test, type APIRequestContext } from '@playwright/test'
import { ADMIN, EMPLOYEE, EMPLOYEE_2FA, resetSecondFactors, signIn, signOut, unique } from './helpers'

const BASE = 'dc=heracles,dc=test'
const person = (uid: string) => `uid=${uid},ou=people,${BASE}`

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

test('an access request flows from the portal to the owner and into the directory', async ({ page, baseURL }) => {
  const url = baseURL ?? 'http://localhost:8420'
  await resetSecondFactors(url, EMPLOYEE_2FA.login)
  const { api, csrf } = await adminApi(url)
  const name = unique('e2e-team')
  const created = await api.post('/api/v2/objects/group', {
    data: {
      base: '',
      tabs: { main: { values: { cn: name, member: [person(ADMIN.login)], owner: [person(EMPLOYEE.login)] } } },
    },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const group = ((await created.json()) as { dn: string }).dn

  try {
    // the requester asks from the self-service portal
    await signIn(page, EMPLOYEE_2FA.login, EMPLOYEE_2FA.password)
    await expect(page).not.toHaveURL(/\/login/)
    await page.goto('/me')
    await page.getByRole('button', { name: 'Request access' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Group or role').selectOption({ label: name })
    await dialog.getByLabel('Why do you need it?').fill('Joining the project')
    const until = new Date(Date.now() + 20 * 86_400_000).toISOString().slice(0, 10)
    await dialog.getByLabel('Until').fill(until)
    await dialog.getByRole('button', { name: 'Send request' }).click()
    await expect(page.locator('li', { hasText: name }).getByText('Waiting for approval', { exact: false })).toBeVisible()
    await signOut(page)

    // the owner (a portal user) approves it from their own page
    await signIn(page, EMPLOYEE.login, EMPLOYEE.password)
    await expect(page).not.toHaveURL(/\/login/)
    await page.goto('/me')
    const approvals = page.locator('#access-approvals')
    const row = approvals.locator('li', { hasText: `carol asks to join ${name}` })
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: 'Approve' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Approve' }).click()
    await expect(row).toBeHidden()

    // the membership is in the directory, with its end date
    const fetched = await api.get(`/api/v2/objects/group/${encodeURIComponent(group)}`)
    const values = ((await fetched.json()) as { tabs: { main: { values: { member: string[] } } } }).tabs.main.values
    expect(values.member.map((m) => m.toLowerCase())).toContain(person(EMPLOYEE_2FA.login))
    const grants = await api.get(`/api/v2/access/grants?holder=${encodeURIComponent(group)}`)
    const items = ((await grants.json()) as { items: { member: string; until: string }[] }).items
    expect(items.map((i) => i.until.slice(0, 10))).toEqual([until])
  } finally {
    await api.delete(`/api/v2/objects/group/${encodeURIComponent(group)}`, { headers: { 'X-CSRF-Token': await csrf() } })
    await api.dispose()
  }
})

test('owners, end dates and a review campaign in the console', async ({ page, baseURL }) => {
  const url = baseURL ?? 'http://localhost:8420'
  const { api, csrf } = await adminApi(url)
  const name = unique('e2e-review')
  const created = await api.post('/api/v2/objects/group', {
    data: { base: '', tabs: { main: { values: { cn: name, member: [person(ADMIN.login), person(EMPLOYEE.login)] } } } },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const group = ((await created.json()) as { dn: string }).dn

  try {
    await signIn(page, ADMIN.login, ADMIN.password)
    await expect(page).not.toHaveURL(/\/login/)
    await page.goto(`/types/group/${encodeURIComponent(group)}`)

    // the group can be given owners (who approve requests and review it)
    await page.getByRole('tab', { name: 'Properties' }).click()
    await expect(page.getByText('Owners').first()).toBeVisible()
    await page.getByRole('button', { name: 'Edit' }).click()
    await expect(page.getByText('People responsible for the group', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: 'Cancel' }).click()

    // an end date on one membership, shown in the members table
    await page.getByRole('tab', { name: 'Members' }).click()
    await page.getByRole('button', { name: /^Set end date for .*Durand|^Set end date for bob/ }).first().click()
    const dialog = page.getByRole('dialog')
    const until = new Date(Date.now() + 15 * 86_400_000).toISOString().slice(0, 10)
    await dialog.getByLabel('Last day of access').fill(until)
    await dialog.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText(`Until ${until}`)).toBeVisible()

    // a review campaign over the group: remove bob, alice goes by the default (remove)
    await page.goto('/access/reviews')
    await page.getByRole('button', { name: 'New review' }).click()
    const form = page.getByRole('dialog')
    await form.getByLabel('Name').fill(name)
    await form.getByRole('combobox', { name: 'Groups and roles' }).click()
    await page.getByLabel('Search…').fill(name)
    await page.getByRole('option', { name: new RegExp(name) }).click()
    await form.getByLabel('Undecided at close').selectOption('revoke')
    await form.getByLabel('Deadline').fill(new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10))
    await form.getByRole('button', { name: 'Start review' }).click()
    await page.getByRole('link', { name }).click()
    const bobRow = page.getByTestId('review-item').filter({ hasText: person(EMPLOYEE.login) })
    await bobRow.getByRole('button', { name: 'Remove' }).click()
    await expect(bobRow.getByRole('button', { name: 'Remove', pressed: true })).toBeVisible()
    await page.getByRole('button', { name: 'Close review' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Close review' }).click()
    await expect(page.getByText('Removed')).toBeVisible()
    await expect(page.getByText('Kept: last member of the group')).toBeVisible()

    // the report downloads (the sign-in is fresh, so no password prompt)
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: /Report/ }).click()
    await page.getByRole('menuitem', { name: 'JSON (with hash)' }).click()
    expect((await download).suggestedFilename()).toMatch(/^access-review-.*\.json$/)

    // the console page for requests answers too
    await page.goto('/access/requests')
    await expect(page.getByRole('heading', { name: 'Access requests', level: 1 })).toBeVisible()
  } finally {
    await api.delete(`/api/v2/objects/group/${encodeURIComponent(group)}`, { headers: { 'X-CSRF-Token': await csrf() } })
    await api.dispose()
  }
})

test('role occupants get end dates from the role’s “Access ends” tab', async ({ page, baseURL }) => {
  const url = baseURL ?? 'http://localhost:8420'
  const { api, csrf } = await adminApi(url)
  const name = unique('e2e-occupants')
  const created = await api.post('/api/v2/objects/role', {
    data: { base: '', tabs: { main: { values: { cn: name, roleOccupant: [person(EMPLOYEE.login)] } } } },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const role = ((await created.json()) as { dn: string }).dn

  try {
    await signIn(page, ADMIN.login, ADMIN.password)
    await expect(page).not.toHaveURL(/\/login/)
    await page.goto(`/types/role/${encodeURIComponent(role)}`)
    await page.getByRole('tab', { name: 'Access ends' }).click()
    const row = page.locator('tr', { hasText: EMPLOYEE.login })
    await expect(row.getByText('No end date')).toBeVisible()

    await row.getByRole('button', { name: `Set end date for ${EMPLOYEE.login}` }).click()
    const dialog = page.getByRole('dialog')
    const until = new Date(Date.now() + 12 * 86_400_000).toISOString().slice(0, 10)
    await dialog.getByLabel('Last day of access').fill(until)
    await dialog.getByRole('button', { name: 'Save' }).click()
    await expect(row.getByText(`Until ${until}`)).toBeVisible()

    // stored on the role entry, kind roleOccupant
    const grants = await api.get(`/api/v2/access/grants?holder=${encodeURIComponent(role)}`)
    const items = ((await grants.json()) as { items: { kind: string; member: string; until: string }[] }).items
    expect(items.map((i) => [i.kind, i.member.toLowerCase(), i.until.slice(0, 10)])).toEqual([
      ['roleOccupant', person(EMPLOYEE.login), until],
    ])

    // and it can be made permanent again
    await row.getByRole('button', { name: `Set end date for ${EMPLOYEE.login}` }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Remove end date' }).click()
    await expect(row.getByText('No end date')).toBeVisible()
  } finally {
    await api.delete(`/api/v2/objects/role/${encodeURIComponent(role)}`, { headers: { 'X-CSRF-Token': await csrf() } })
    await api.dispose()
  }
})

test('an ACL assignment member gets an end date in “Who has access”', async ({ page, baseURL }) => {
  const url = baseURL ?? 'http://localhost:8420'
  const { api, csrf } = await adminApi(url)
  const name = unique('e2e-acl')
  const group = await api.post('/api/v2/objects/group', {
    data: { base: '', tabs: { main: { values: { cn: name, member: [person(ADMIN.login)] } } } },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(group.ok(), await group.text()).toBeTruthy()
  const holder = ((await group.json()) as { dn: string }).dn
  const aclRole = await api.post('/api/v2/admin/acl/roles', {
    data: {
      cn: name,
      description: 'Created by the browser tests',
      templates: [{ index: 0, blocks: [{ object: 'user', rights: 'r', attributes: [] }] }],
    },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(aclRole.ok(), await aclRole.text()).toBeTruthy()
  const roleDn = ((await aclRole.json()) as { dn: string }).dn
  const assigned = await api.put(`/api/v2/admin/acl/assignments/${encodeURIComponent(holder)}`, {
    data: { assignments: [{ index: 0, scope: 'subtree', role: roleDn, members: [{ dn: person(EMPLOYEE.login), kind: 'user' }] }] },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(assigned.ok(), await assigned.text()).toBeTruthy()

  try {
    await signIn(page, ADMIN.login, ADMIN.password)
    await expect(page).not.toHaveURL(/\/login/)
    await page.goto('/admin/access')
    await page.getByRole('tab', { name: 'Who has access' }).click()
    const row = page.getByRole('listitem').filter({ hasText: name }).filter({ hasText: EMPLOYEE.login })
    await expect(row).toBeVisible()

    await row.getByRole('button', { name: `Set end date for ${EMPLOYEE.login}` }).click()
    const dialog = page.getByRole('dialog')
    const until = new Date(Date.now() + 25 * 86_400_000).toISOString().slice(0, 10)
    await dialog.getByLabel('Last day of access').fill(until)
    await dialog.getByRole('button', { name: 'Save' }).click()
    await expect(row.getByText(`Until ${until}`)).toBeVisible()

    const grants = await api.get(`/api/v2/access/grants?holder=${encodeURIComponent(holder)}`)
    const items = (
      (await grants.json()) as { items: { kind: string; member: string; until: string; acl_scope?: string; acl_role?: string }[] }
    ).items
    expect(items.map((i) => [i.kind, i.member.toLowerCase(), i.acl_scope, i.acl_role?.toLowerCase(), i.until.slice(0, 10)])).toEqual([
      ['acl', person(EMPLOYEE.login), 'subtree', roleDn.toLowerCase(), until],
    ])

    // it survives a reload (read back from the directory)
    await page.reload()
    await page.getByRole('tab', { name: 'Who has access' }).click()
    await expect(row.getByText(`Until ${until}`)).toBeVisible()
  } finally {
    await api.delete(`/api/v2/objects/group/${encodeURIComponent(holder)}`, { headers: { 'X-CSRF-Token': await csrf() } })
    await api.delete(`/api/v2/admin/acl/roles/${encodeURIComponent(roleDn)}`, { headers: { 'X-CSRF-Token': await csrf() } })
    await api.dispose()
  }
})

test('a console user requests access for someone else', async ({ page, baseURL }) => {
  const url = baseURL ?? 'http://localhost:8420'
  const { api, csrf } = await adminApi(url)
  const name = unique('e2e-for')
  const created = await api.post('/api/v2/objects/group', {
    data: { base: '', tabs: { main: { values: { cn: name, member: [person(EMPLOYEE_2FA.login)], owner: [person(ADMIN.login)] } } } },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(created.ok(), await created.text()).toBeTruthy()
  const group = ((await created.json()) as { dn: string }).dn

  try {
    await signIn(page, ADMIN.login, ADMIN.password)
    await expect(page).not.toHaveURL(/\/login/)
    await page.goto('/access/requests')
    await page.getByRole('button', { name: 'Request access' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('combobox', { name: 'For' }).click()
    await page.getByLabel('Search…').fill(EMPLOYEE.login)
    await page.getByRole('option', { name: new RegExp(person(EMPLOYEE.login)) }).click()
    await expect(dialog.getByTestId('req-member-chosen')).toHaveText(EMPLOYEE.login)
    await dialog.getByLabel('Group or role').selectOption({ label: name })
    await dialog.getByLabel('Why do you need it?').fill('Asked by their lead')
    await dialog.getByLabel('Until').fill(new Date(Date.now() + 20 * 86_400_000).toISOString().slice(0, 10))
    await dialog.getByRole('button', { name: 'Send request' }).click()
    await expect(dialog).toBeHidden()

    // the request names the person it is for and the one who asked
    const listed = await api.get('/api/v2/access/requests?view=mine')
    const items = (
      (await listed.json()) as {
        items: { id: string; member: string; requester: string; status: string; target: { dn: string } }[]
      }
    ).items.filter((r) => r.target.dn.toLowerCase() === group.toLowerCase())
    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ status: 'pending' })
    expect(items[0]?.member.toLowerCase()).toBe(person(EMPLOYEE.login))
    expect(items[0]?.requester.toLowerCase()).toBe(person(ADMIN.login))
    const cancelled = await api.post(`/api/v2/access/requests/${items[0]?.id}/cancel`, { headers: { 'X-CSRF-Token': await csrf() } })
    expect(cancelled.ok(), await cancelled.text()).toBeTruthy()
  } finally {
    await api.delete(`/api/v2/objects/group/${encodeURIComponent(group)}`, { headers: { 'X-CSRF-Token': await csrf() } })
    await api.dispose()
  }
})

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

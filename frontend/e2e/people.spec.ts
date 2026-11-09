import { expect, test } from '@playwright/test'
import { ADMIN, signIn, unique } from './helpers'

test('onboard a person with the wizard, lock and unlock, then delete', async ({ page }) => {
  const login = unique('e2e')
  const lastName = `Tester${login.slice(-6)}`
  await signIn(page, ADMIN.login, ADMIN.password)
  await expect(page.getByRole('heading', { name: /^Good / })).toBeVisible()

  // 1. identity
  await page.goto('/types/user/new')
  await page.getByLabel('First name').fill('Erin')
  await page.getByLabel('Last name').fill(lastName)
  await page.getByLabel('Login (username)').fill(login)
  await page.getByRole('button', { name: 'Next step' }).click()
  // 2. department and groups: join "staff"
  await page.getByRole('checkbox', { name: /staff/ }).check()
  await page.getByRole('button', { name: 'Next step' }).click()
  // 3. password
  await page.getByLabel('Password', { exact: true }).fill('E2e-Secret-pass-123!')
  await page.getByRole('button', { name: 'Next step' }).click()
  // 4. review and create
  await expect(page.getByText(login).first()).toBeVisible()
  await page.getByRole('button', { name: 'Create user' }).click()

  // profile of the new person
  await expect(page.getByRole('heading', { name: `Erin ${lastName}` })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/types/user/uid%3D${login}`))
  await expect(page.getByText('staff').first()).toBeVisible()

  // lock, then unlock
  await page.getByRole('button', { name: 'Lock account' }).click()
  await expect(page.locator('[data-status="locked"]').first()).toBeVisible()
  await page.getByRole('button', { name: 'Unlock account' }).click()
  await expect(page.locator('[data-status="active"]').first()).toBeVisible()

  // the person shows up in the list with the group count
  await page.goto('/types/user')
  const row = page.getByRole('row', { name: new RegExp(login) })
  await expect(row).toBeVisible()
  await expect(row.getByText('1', { exact: true })).toBeVisible()

  // delete, with typed confirmation
  await row.getByRole('link', { name: new RegExp(lastName) }).click()
  await page.getByRole('button', { name: 'More actions' }).click()
  await page.getByRole('menuitem', { name: /Delete user/ }).click()
  const dialog = page.getByRole('alertdialog')
  await dialog.getByRole('textbox').fill(login)
  await dialog.getByRole('button', { name: 'Delete user' }).click()
  await expect(page).toHaveURL(/\/types\/user$/)
  await expect(page.getByRole('row', { name: new RegExp(login) })).toHaveCount(0)
})

test('every extra settings tab of a person opens in the full editor', async ({ page }) => {
  await signIn(page, ADMIN.login, ADMIN.password)
  await expect(page.getByRole('heading', { name: /^Good / })).toBeVisible()
  await page.goto(`/types/user/${encodeURIComponent('uid=bob,ou=people,dc=heracles,dc=test')}`)
  await page.getByRole('tab', { name: 'Advanced' }).click()
  const unix = page.getByRole('listitem').filter({ hasText: 'Unix' })
  await expect(unix).toBeVisible()
  await unix.getByRole('link').click()
  await expect(page).toHaveURL(/view=generic/)
  await expect(page).toHaveURL(/tab=posix/)
  await expect(page.getByRole('tab', { name: /Unix/, selected: true })).toBeVisible()
})

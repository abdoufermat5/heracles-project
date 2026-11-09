import { expect, test } from '@playwright/test'
import { ADMIN, EMPLOYEE, signIn, signOut } from './helpers'

test('administrators get the console, grouped by task, with the work queue', async ({ page }) => {
  await signIn(page, ADMIN.login, ADMIN.password)
  await expect(page.getByRole('heading', { name: /^Good (morning|afternoon|evening)/ })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Needs attention' })).toBeVisible()
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  for (const section of ['People', 'Organization', 'Access', 'Administration'])
    await expect(nav.getByRole('heading', { name: section })).toBeVisible()
  await expect(nav.getByRole('link', { name: /Users/ })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Access control' })).toBeVisible()
  await signOut(page)
})

test('people who only manage themselves get the portal with real data only', async ({ page }) => {
  await signIn(page, EMPLOYEE.login, EMPLOYEE.password)
  await expect(page).toHaveURL(/\/me$/)
  await expect(page.getByRole('heading', { name: /Hello, Bob/ })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toHaveCount(0)
  // console pages lead back to the portal
  await page.goto('/types/user')
  await expect(page).toHaveURL(/\/me$/)
  // nothing invented: the seed account's address is on heracles.test
  await expect(page.getByText(/@example\.com/)).toHaveCount(0)
  // his own groups show even without read rights on the group entries
  const groups = page.locator('#portal-groups')
  await expect(groups.getByText('staff')).toBeVisible()
  await expect(groups.getByText('Something went wrong')).toHaveCount(0)
  await signOut(page)
})

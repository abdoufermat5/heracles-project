import { expect, test } from '@playwright/test'
import { signOut } from './helpers'

// The test identity provider of the `oidc` compose profile (deploy/e2e/oidc-realm.json).
const DISCOVERY = 'http://127.0.0.1:8180/realms/heracles/.well-known/openid-configuration'
const PERSON = { login: 'alice', password: 'alice-at-the-idp', name: 'Alice Martin' }

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

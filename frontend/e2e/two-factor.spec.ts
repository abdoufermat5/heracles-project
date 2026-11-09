import { expect, test } from '@playwright/test'
import { EMPLOYEE_2FA, nextTotpStep, resetSecondFactors, signIn, signOut, totp } from './helpers'

test.setTimeout(150_000)

test.beforeEach(async ({ baseURL }) => {
  await resetSecondFactors(baseURL ?? 'http://localhost:8420', EMPLOYEE_2FA.login)
})

test('an employee sets up an authenticator app, then signs in with it', async ({ page }) => {
  await signIn(page, EMPLOYEE_2FA.login, EMPLOYEE_2FA.password)
  await expect(page).toHaveURL(/\/me$/)

  await page.getByRole('button', { name: 'Set up authenticator app' }).click()
  const secret = (await page.getByTestId('totp-secret').textContent())?.trim() ?? ''
  expect(secret).toMatch(/^[A-Z2-7]{16,}$/)
  await page.getByLabel('Verification code').fill(totp(secret))
  await page.getByRole('button', { name: 'Verify and enable' }).click()
  await expect(page.getByText('Enabled.')).toBeVisible()
  await signOut(page)

  // the password alone no longer opens the session
  await signIn(page, EMPLOYEE_2FA.login, EMPLOYEE_2FA.password)
  await expect(page).toHaveURL(/second-factor/)
  await nextTotpStep(page) // the enrolment code must not be accepted twice
  await page.getByRole('textbox').first().click()
  await page.keyboard.type(totp(secret))
  await page.getByRole('button', { name: 'Verify' }).click()
  await expect(page).toHaveURL(/\/me$/)

  // turn it off again: it is the only second factor, so confirm
  await page.getByRole('button', { name: 'Disable authenticator app' }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Disable and turn off' }).click()
  await expect(page.getByText('Not set up.')).toBeVisible()
})

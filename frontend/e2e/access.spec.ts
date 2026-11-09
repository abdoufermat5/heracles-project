import { expect, test } from '@playwright/test'
import { ADMIN, signIn, unique } from './helpers'

test('build a role in the permission matrix; the rights survive a reload', async ({ page }) => {
  const name = unique('e2e-role')
  await signIn(page, ADMIN.login, ADMIN.password)
  await expect(page.getByRole('heading', { name: /^Good / })).toBeVisible()
  await page.goto('/admin/access')

  await page.getByRole('button', { name: 'New role' }).first().click()
  const editor = page.getByRole('dialog')
  await editor.getByLabel('Name', { exact: true }).fill(name)
  await editor.getByLabel('Description').fill('Created by the browser tests')
  const view = editor.getByRole('checkbox', { name: /^User.* — view$/ }).first()
  const edit = editor.getByRole('checkbox', { name: /^User.* — edit$/ }).first()
  await view.check()
  await edit.check()
  await editor.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(editor).toBeHidden()

  // the card reads in plain words, and the stored rights come back as ticked
  await expect(page.getByText(name).first()).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: `Edit role ${name}` }).click()
  const reopened = page.getByRole('dialog')
  await expect(reopened.getByRole('checkbox', { name: /^User.* — view$/ }).first()).toBeChecked()
  await expect(reopened.getByRole('checkbox', { name: /^User.* — edit$/ }).first()).toBeChecked()
  await expect(reopened.getByRole('checkbox', { name: /^User.* — delete$/ }).first()).not.toBeChecked()
  await reopened.getByRole('button', { name: 'Cancel' }).click()

  // clean up
  await page.getByRole('button', { name: `Delete role ${name}` }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete role' }).click()
  await expect(page.getByText(name)).toHaveCount(0)
})

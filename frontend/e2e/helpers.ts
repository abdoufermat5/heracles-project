import { createHmac, randomBytes } from 'node:crypto'
import { expect, request, type Page } from '@playwright/test'

/** Accounts of the test directory (deploy/ldap/seed.ldif). */
export const ADMIN = { login: 'alice', password: 'alice-secret' }
export const EMPLOYEE = { login: 'bob', password: 'bob-secret' }
export const EMPLOYEE_2FA = { login: 'carol', password: 'carol-secret' }

export function unique(prefix: string): string {
  return `${prefix}-${randomBytes(3).toString('hex')}`
}

export async function signIn(page: Page, login: string, password: string): Promise<void> {
  await page.goto('/login')
  await page.locator('#username').fill(login)
  await page.locator('#password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

export async function signOut(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'User menu' }).click()
  await page.getByRole('menuitem', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login/)
}

function base32Decode(text: string): Buffer {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const ch of text.replace(/=+$/, '').toUpperCase())
    bits += alphabet.indexOf(ch).toString(2).padStart(5, '0')
  const bytes: number[] = []
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2))
  return Buffer.from(bytes)
}

/** RFC 6238 code (SHA-1, 30 s, 6 digits) of `secret` at `at` (ms). */
export function totp(secret: string, at = Date.now()): string {
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)))
  const mac = createHmac('sha1', base32Decode(secret)).update(counter).digest()
  const offset = mac[mac.length - 1]! & 0x0f
  const value = (mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000
  return value.toString().padStart(6, '0')
}

/** Wait for the next 30-second step, so a fresh code is not a replay. */
export async function nextTotpStep(page: Page): Promise<void> {
  await page.waitForTimeout(30_000 - (Date.now() % 30_000) + 500)
}

/** Remove every second factor of `login` through the administration API (test isolation). */
export async function resetSecondFactors(baseURL: string, login: string): Promise<void> {
  const api = await request.newContext({ baseURL })
  const csrf = async () => ((await (await api.get('/api/v2/auth/csrf')).json()) as { token: string }).token
  const r = await api.post('/api/v2/auth/login', {
    data: { directory: 'main', username: ADMIN.login, password: ADMIN.password },
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect(r.ok()).toBeTruthy()
  const dn = `uid=${login},ou=people,dc=heracles,dc=test`
  const reset = await api.delete(`/api/v2/users/${encodeURIComponent(dn)}/second-factors`, {
    headers: { 'X-CSRF-Token': await csrf() },
  })
  expect([204, 404]).toContain(reset.status())
  await api.dispose()
}

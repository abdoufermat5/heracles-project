import { expect, request, test, type APIRequestContext } from '@playwright/test'
import { ADMIN, unique } from './helpers'

/**
 * Cross-replica state. Runs only against the replicas stack (`make e2e-replicas`): the base URL
 * is the load balancer and HERACLES_E2E_REPLICAS lists the two replicas, e.g.
 * `http://localhost:8421,http://localhost:8422`.
 */
const replicas = (process.env.HERACLES_E2E_REPLICAS ?? '').split(',').filter(Boolean)

test.skip(replicas.length !== 2, 'needs the replicas stack (make e2e-replicas)')

const token = async (api: APIRequestContext) =>
  ((await (await api.get('/api/v2/auth/csrf')).json()) as { token: string }).token

test('a session started on the balancer works on every replica; an edit shows on the other', async ({
  baseURL,
}) => {
  const [first, second] = replicas as [string, string]
  const balancer = await request.newContext({ baseURL })
  const login = await balancer.post('/api/v2/auth/login', {
    data: { directory: 'main', username: ADMIN.login, password: ADMIN.password },
    headers: { 'X-CSRF-Token': await token(balancer) },
  })
  expect(login.ok()).toBeTruthy()
  const { cookies } = await balancer.storageState()

  // the same cookies, presented straight to each replica
  const one = await request.newContext({ baseURL: first, storageState: { cookies, origins: [] } })
  const two = await request.newContext({ baseURL: second, storageState: { cookies, origins: [] } })
  for (const api of [one, two]) expect((await api.get('/api/v2/auth/me')).status()).toBe(200)

  // an edit through replica 1 is visible through replica 2 (then put back)
  const surname = unique('Replica')
  const url = `/api/v2/objects/user/${encodeURIComponent('uid=bob,ou=people,dc=heracles,dc=test')}`
  const set = async (value: string) =>
    one.patch(url, {
      data: { tabs: { main: { values: { sn: value } } } },
      headers: { 'X-CSRF-Token': await token(one) },
    })
  const patch = await set(surname)
  expect(patch.ok(), await patch.text()).toBeTruthy()
  try {
    const seen = (await (await two.get(url)).json()) as { tabs: { main: { values: { sn: string } } } }
    expect(seen.tabs.main.values.sn).toBe(surname)
  } finally {
    await set('Durand')
  }

  await Promise.all([balancer.dispose(), one.dispose(), two.dispose()])
})

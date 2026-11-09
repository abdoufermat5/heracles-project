import { defineConfig } from '@playwright/test'

/**
 * Browser end-to-end tests against a running stack (`make dev` or `make e2e`):
 * the API container serves the built UI on HERACLES_E2E_URL.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1, // the specs share one directory
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.HERACLES_E2E_URL ?? 'http://localhost:8420',
    channel: process.env.PLAYWRIGHT_CHANNEL ?? 'chrome',
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
})

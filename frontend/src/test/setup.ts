import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import i18n from '@/i18n'
import { resetCsrf } from '@/api/client'
import { db } from '@/mocks/db'
import { server } from '@/mocks/server'

// Parallel test files starve each other of CPU: the default 1 s is too tight for first renders.
configure({ asyncUtilTimeout: 5000 })

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= RO as unknown as typeof ResizeObserver
window.matchMedia ??= ((q: string) => ({
  matches: false,
  media: q,
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
  dispatchEvent: () => false,
  onchange: null,
})) as unknown as typeof window.matchMedia
Element.prototype.scrollIntoView ??= () => {}
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.releasePointerCapture ??= () => {}

beforeAll(async () => {
  await i18n.changeLanguage('en')
  server.listen({ onUnhandledFrame: 'error' })
})
afterEach(() => {
  cleanup()
  server.resetHandlers()
  db.reset()
  resetCsrf()
  localStorage.clear()
})
afterAll(() => server.close())

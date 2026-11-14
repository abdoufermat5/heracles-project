import { setupWorker } from 'msw/browser'
import { handlers, restoreMockSession } from './handlers'
import { objectsHandlers, seedDemoTemplates } from './objectsHandlers'
import { setupHandlers } from './setupHandlers'

/**
 * Named request handlers are installed once per page: a second `setupWorker().start()`
 * throws (`WebSocket` is already intercepted), which blanked the page after every hot
 * update in mock mode. The promise is kept so a repeated bootstrap awaits the same start.
 */
let started: Promise<void> | null = null

export function startMockWorker(): Promise<void> {
  if (!started) {
    restoreMockSession()
    seedDemoTemplates()
    const worker = setupWorker(...setupHandlers, ...objectsHandlers, ...handlers)
    started = worker
      .start({ onUnhandledFrame: 'bypass', quiet: true })
      .then(() => undefined)
  }
  return started
}

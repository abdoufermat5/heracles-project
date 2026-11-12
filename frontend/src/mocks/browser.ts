import { setupWorker } from 'msw/browser'
import { handlers, restoreMockSession } from './handlers'
import { objectsHandlers, seedDemoTemplates } from './objectsHandlers'
import { setupHandlers } from './setupHandlers'

export async function startMockWorker(): Promise<void> {
  restoreMockSession()
  seedDemoTemplates()
  const worker = setupWorker(...setupHandlers, ...objectsHandlers, ...handlers)
  await worker.start({ onUnhandledFrame: 'bypass', quiet: true })
}

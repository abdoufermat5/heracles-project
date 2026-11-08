import { setupWorker } from 'msw/browser'
import { handlers, restoreMockSession } from './handlers'
import { objectsHandlers, seedDemoTemplates } from './objectsHandlers'

export async function startMockWorker(): Promise<void> {
  restoreMockSession()
  seedDemoTemplates()
  const worker = setupWorker(...objectsHandlers, ...handlers)
  await worker.start({ onUnhandledFrame: 'bypass', quiet: true })
}

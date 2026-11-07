import { setupWorker } from 'msw/browser'
import { handlers, restoreMockSession } from './handlers'

export async function startMockWorker(): Promise<void> {
  restoreMockSession()
  const worker = setupWorker(...handlers)
  await worker.start({ onUnhandledFrame: 'bypass', quiet: true })
}

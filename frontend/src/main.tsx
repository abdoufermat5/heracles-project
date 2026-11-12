import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { AppErrorBoundary } from './components/resilience'
import { i18nReady } from './i18n'
import './index.css'

async function bootstrap(): Promise<void> {
  const mock = import.meta.env.VITE_API_MOCK ?? (import.meta.env.DEV ? 'true' : 'false')
  if (mock === 'true') {
    const { startMockWorker } = await import('./mocks/browser')
    await startMockWorker()
  }
  // French users must not see an English flash: wait for the lazy French bundle.
  await i18nReady
  const el = document.getElementById('root')
  if (!el) throw new Error('missing #root')
  createRoot(el).render(
    <StrictMode>
      <AppErrorBoundary>
        <App />
      </AppErrorBoundary>
    </StrictMode>,
  )
}

void bootstrap()

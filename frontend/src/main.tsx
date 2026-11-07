import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './i18n'
import './index.css'

async function bootstrap(): Promise<void> {
  const mock = import.meta.env.VITE_API_MOCK ?? (import.meta.env.DEV ? 'true' : 'false')
  if (mock === 'true') {
    const { startMockWorker } = await import('./mocks/browser')
    await startMockWorker()
  }
  const el = document.getElementById('root')
  if (!el) throw new Error('missing #root')
  createRoot(el).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

void bootstrap()

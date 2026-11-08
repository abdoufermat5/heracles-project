import { useEffect } from 'react'
import { useCapabilities } from '@/features/admin/hooks'
import { setTechnicalDefault } from '@/lib/preferences'
import { AppShell } from './AppShell'
import { PortalShell } from './PortalShell'

/**
 * People who manage others get the administration console; everyone else gets
 * the self-service portal. Capabilities are preloaded by the route, so the
 * right shell renders on the first paint.
 */
export function WorkspaceShell() {
  const { data: caps } = useCapabilities()
  const isConsole = caps?.console ?? true

  useEffect(() => {
    // technical staff work in the console: show directory internals by default
    setTechnicalDefault(isConsole)
  }, [isConsole])

  return isConsole ? <AppShell /> : <PortalShell />
}

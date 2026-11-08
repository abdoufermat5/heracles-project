/**
 * Trigger output returned by write endpoints (`warnings`, `messages`).
 *
 * Triggers are commands configured in the directory: their output is shown as it
 * is, never translated. `messages` only appear when the configuration asks for it.
 */
import { toast } from 'sonner'

export interface TriggerOutput {
  warnings?: string[]
  messages?: string[]
}

export function showTriggerOutput(result: TriggerOutput | undefined | null): void {
  if (!result) return
  for (const warning of result.warnings ?? []) toast.warning(warning)
  for (const message of result.messages ?? []) toast.message(message)
}

/**
 * Client-side rules of a trigger, mirroring `heracles.triggers.check_hook_fields` and the
 * checks of `PUT /admin/hooks`: a value refused here is refused by the server too.
 */
import i18n from 'i18next'
import type { Hook } from './types'

/** Longest command the server stores. */
export const MAX_COMMAND_LENGTH = 1000

export type HookField = 'tab' | 'mode' | 'command'
export type HookErrors = Partial<Record<HookField, string>>

const t = (key: string, opts?: Record<string, unknown>): string => i18n.t(key, opts)

/**
 * Problems of one trigger. `others` are the triggers it must differ from; `tabs` and `modes`
 * are what the server offers (a tab already stored stays valid, so callers pass it in `tabs`).
 */
export function checkHook(
  hook: Hook,
  others: readonly Hook[],
  tabs: readonly string[],
  modes: readonly string[],
): HookErrors {
  const errors: HookErrors = {}
  const tab = hook.tab.trim()
  if (!tab) errors.tab = t('hooks.errors.tabRequired')
  else if (/[|\r\n\0]/.test(tab) || !tabs.includes(tab)) errors.tab = t('hooks.errors.tabUnknown')
  if (!modes.includes(hook.mode)) errors.mode = t('hooks.errors.modeRequired')
  const command = hook.command.trim()
  if (!command) errors.command = t('hooks.errors.commandRequired')
  else if (/[\r\n\0]/.test(command)) errors.command = t('hooks.errors.commandMultiline')
  else if (command.startsWith('#')) errors.command = t('hooks.errors.commandHash')
  else if (command.length > MAX_COMMAND_LENGTH)
    errors.command = t('validation.maxLength', { count: MAX_COMMAND_LENGTH })
  if (
    !errors.tab &&
    !errors.mode &&
    !errors.command &&
    others.some((o) => o.tab.trim() === tab && o.mode === hook.mode && o.command.trim() === command)
  )
    errors.command = t('hooks.errors.duplicate')
  return errors
}

/** Errors of a whole list by row index; a duplicate is reported on the later row, as the server does. */
export function checkHooks(
  rows: readonly Hook[],
  tabs: readonly string[],
  modes: readonly string[],
): Record<number, HookErrors> {
  const out: Record<number, HookErrors> = {}
  rows.forEach((hook, i) => {
    const errors = checkHook(hook, rows.slice(0, i), tabs, modes)
    if (Object.keys(errors).length > 0) out[i] = errors
  })
  return out
}

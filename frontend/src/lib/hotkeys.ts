import { useEffect, useRef, useSyncExternalStore } from 'react'

/**
 * Tiny keyboard-shortcut layer.
 *
 * A combo is one key (`/`, `?`, `mod+k`) or a sequence of keys separated by spaces
 * (`g d`). `mod` is Ctrl or Cmd. Plain keys and sequences are ignored while the
 * user types in a field; `mod+` combos always fire.
 *
 * Features register shortcuts with `useHotkey`; the `?` sheet lists them by scope.
 */

export interface HotkeyOptions {
  /** Shown in the shortcut sheet; shortcuts without a description are not listed. */
  description?: string
  /** Group in the shortcut sheet (`global`, `navigation`, or a page name). */
  scope?: string
  enabled?: boolean
}

export interface HotkeyEntry {
  id: number
  combo: string
  description?: string
  scope: string
  handler: (e: KeyboardEvent) => void
}

/** Time allowed between the keys of a sequence. */
export const SEQUENCE_TIMEOUT_MS = 1000

let nextId = 1
let entries: HotkeyEntry[] = []
const listeners = new Set<() => void>()
let buffer: string[] = []
let timer: ReturnType<typeof setTimeout> | undefined

function emit(): void {
  listeners.forEach((l) => l())
}

export function normalizeCombo(combo: string): string[] {
  return combo
    .trim()
    .split(/\s+/)
    .map((k) => k.toLowerCase())
}

/** Register a shortcut; returns the function that removes it. */
export function registerHotkey(
  combo: string,
  handler: (e: KeyboardEvent) => void,
  opts: HotkeyOptions = {},
): () => void {
  const entry: HotkeyEntry = {
    id: nextId++,
    combo: normalizeCombo(combo).join(' '),
    description: opts.description,
    scope: opts.scope ?? 'global',
    handler,
  }
  entries = [...entries, entry]
  emit()
  return () => {
    entries = entries.filter((e) => e.id !== entry.id)
    emit()
  }
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

function tokenOf(e: KeyboardEvent): string | null {
  if (e.key === 'Shift' || e.key === 'Control' || e.key === 'Meta' || e.key === 'Alt') return null
  const key = e.key === 'Escape' ? 'esc' : e.key.toLowerCase()
  return e.ctrlKey || e.metaKey ? `mod+${key}` : key
}

function resetBuffer(): void {
  buffer = []
  clearTimeout(timer)
  timer = undefined
}

/** Dispatch one keydown; exported for the global listener and tests. */
export function handleKeyDown(e: KeyboardEvent): void {
  if (e.defaultPrevented || e.altKey) return
  const token = tokenOf(e)
  if (!token) return
  if (!token.startsWith('mod+') && isTypingTarget(e.target)) {
    resetBuffer()
    return
  }
  const attempt = (seq: string[]): 'fired' | 'pending' | 'none' => {
    const joined = seq.join(' ')
    const exact = [...entries].reverse().find((en) => en.combo === joined)
    const longer = entries.some((en) => en.combo.startsWith(`${joined} `))
    if (longer) {
      buffer = seq
      clearTimeout(timer)
      timer = setTimeout(resetBuffer, SEQUENCE_TIMEOUT_MS)
      return 'pending'
    }
    if (exact) {
      resetBuffer()
      e.preventDefault()
      exact.handler(e)
      return 'fired'
    }
    return 'none'
  }
  if (attempt([...buffer, token]) !== 'none') return
  const hadBuffer = buffer.length > 0
  resetBuffer()
  if (hadBuffer) attempt([token])
}

/** Installs the single window listener; mount once, in the shell. */
export function useGlobalHotkeys(): void {
  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      resetBuffer()
    }
  }, [])
}

/** Register a shortcut for the lifetime of the calling component. */
export function useHotkey(
  combo: string,
  handler: (e: KeyboardEvent) => void,
  opts: HotkeyOptions = {},
): void {
  const ref = useRef(handler)
  useEffect(() => {
    ref.current = handler
  })
  const { description, scope, enabled = true } = opts
  useEffect(() => {
    if (!enabled) return
    return registerHotkey(combo, (e) => ref.current(e), { description, scope })
  }, [combo, description, scope, enabled])
}

function subscribe(l: () => void): () => void {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** Every registered shortcut (the `?` sheet lists the described ones). */
export function useHotkeyList(): HotkeyEntry[] {
  return useSyncExternalStore(subscribe, () => entries)
}

/** `g d` -> ['G', 'D']; `mod+k` -> ['Ctrl', 'K'] (or the Cmd sign on Apple platforms). */
export function comboLabels(combo: string): string[] {
  const apple = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
  return normalizeCombo(combo).flatMap((part) =>
    part.split('+').map((k) => {
      if (k === 'mod') return apple ? '⌘' : 'Ctrl'
      if (k === 'esc') return 'Esc'
      return k.length === 1 ? k.toUpperCase() : k
    }),
  )
}

/** Focus the page's search field (`data-hotkey-search`, else the first search input in main). */
export function focusPageSearch(): boolean {
  const el =
    document.querySelector<HTMLElement>('[data-hotkey-search]') ??
    document.querySelector<HTMLElement>('main input[type="search"], main input[role="searchbox"]')
  if (!el) return false
  el.focus()
  if (el instanceof HTMLInputElement) el.select()
  return true
}

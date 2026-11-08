import { useSyncExternalStore } from 'react'

/**
 * Per-browser display preferences.
 *
 * "Technical details" shows directory internals (distinguished names, attribute
 * names) next to the plain-language labels. The administration console is used
 * by technical staff, so it defaults to on there; the self-service portal never
 * shows them. An explicit choice of the viewer always wins.
 */
const TECHNICAL_KEY = 'heracles.technicalDetails'
const listeners = new Set<() => void>()

function readStored(): boolean | null {
  try {
    const v = localStorage.getItem(TECHNICAL_KEY)
    return v === '1' ? true : v === '0' ? false : null
  } catch {
    return null
  }
}

let stored = readStored()
let fallback = false

function notify(): void {
  for (const l of listeners) l()
}

/** The viewer's own choice (remembered in this browser). */
export function setTechnicalDetails(on: boolean): void {
  try {
    localStorage.setItem(TECHNICAL_KEY, on ? '1' : '0')
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
  stored = on
  notify()
}

/** Default when the viewer made no choice: on in the console, off in the portal. */
export function setTechnicalDefault(on: boolean): void {
  if (fallback === on) return
  fallback = on
  notify()
}

function snapshot(): boolean {
  return stored ?? fallback
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Whether directory internals (DNs, attribute names) should be shown. */
export function useTechnicalDetails(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => false)
}

import { useSyncExternalStore } from 'react'

/**
 * Per-browser display preferences.
 *
 * "Technical details" reveals directory internals (distinguished names, attribute
 * names, raw tabs) that the console hides by default so it reads as plain language.
 */
const TECHNICAL_KEY = 'heracles.technicalDetails'
const listeners = new Set<() => void>()

function readTechnical(): boolean {
  try {
    return localStorage.getItem(TECHNICAL_KEY) === '1'
  } catch {
    return false
  }
}

export function setTechnicalDetails(on: boolean): void {
  try {
    localStorage.setItem(TECHNICAL_KEY, on ? '1' : '0')
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
  current = on
  for (const l of listeners) l()
}

let current = readTechnical()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Whether directory internals (DNs, attribute names) should be shown. */
export function useTechnicalDetails(): boolean {
  return useSyncExternalStore(subscribe, () => current, () => false)
}

import { afterEach, describe, expect, it, vi } from 'vitest'
import { handleKeyDown, registerHotkey } from './hotkeys'

function press(key: string, target: EventTarget = document.body, init: KeyboardEventInit = {}) {
  const e = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
  Object.defineProperty(e, 'target', { value: target })
  handleKeyDown(e)
}

const offs: (() => void)[] = []
afterEach(() => {
  offs.splice(0).forEach((off) => off())
  vi.useRealTimers()
})

describe('hotkeys', () => {
  it('fires a key sequence and ignores a broken one', () => {
    const go = vi.fn()
    offs.push(registerHotkey('g u', go, { description: 'users' }))
    press('g')
    press('x')
    press('u')
    expect(go).not.toHaveBeenCalled()
    press('g')
    press('u')
    expect(go).toHaveBeenCalledTimes(1)
  })

  it('drops a half-typed sequence after the timeout', () => {
    vi.useFakeTimers()
    const go = vi.fn()
    offs.push(registerHotkey('g d', go))
    press('g')
    vi.advanceTimersByTime(1500)
    press('d')
    expect(go).not.toHaveBeenCalled()
  })

  it('ignores plain keys while typing, but not mod combos', () => {
    const slash = vi.fn()
    const palette = vi.fn()
    offs.push(registerHotkey('/', slash), registerHotkey('mod+k', palette))
    const input = document.createElement('input')
    document.body.append(input)
    press('/', input)
    press('k', input, { ctrlKey: true })
    input.remove()
    expect(slash).not.toHaveBeenCalled()
    expect(palette).toHaveBeenCalledTimes(1)
  })

  it('unregisters', () => {
    const go = vi.fn()
    registerHotkey('?', go)()
    press('?')
    expect(go).not.toHaveBeenCalled()
  })
})

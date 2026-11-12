import { describe, expect, it } from 'vitest'
import { leadingZeroBits, searchSlice, sha256Short, solveOnMainThread } from './pow'

const hex = (bytes: Uint8Array) => [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')

describe('proof of work', () => {
  it('hashes like SHA-256', () => {
    expect(hex(sha256Short(new TextEncoder().encode('abc')))).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    )
  })

  it('counts leading zero bits', () => {
    expect(leadingZeroBits(new Uint8Array([0, 0x1f]))).toBe(11)
    expect(leadingZeroBits(new Uint8Array([0x80]))).toBe(0)
  })

  it('finds the same counter as the server reference solver', async () => {
    // backend: solve("abc123", 12) == 907
    expect(searchSlice('abc123', 12, 0, 100_000)).toBe(907)
    expect(await solveOnMainThread('abc123', 12)).toBe(907)
  })
})

/**
 * Client side of the proof-of-work challenge of the public forms.
 *
 * The server sends `{nonce, difficulty}`; the answer is a counter such that
 * SHA-256(`${nonce}:${counter}`) starts with `difficulty` zero bits. The search runs in a
 * Web Worker (the page stays responsive); without Worker support it runs on the main thread
 * in short slices that yield to the browser between them. Nothing leaves the page: the
 * challenge is self-hosted, no third-party service is involved.
 */

export interface PowChallenge {
  token: string
  nonce: string
  difficulty: number
  algorithm: 'sha256'
  min_fill_seconds: number
}

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])

const W = new Uint32Array(64)

/** SHA-256 of a short message (under 56 bytes: one block). Synchronous, allocation-light. */
export function sha256Short(message: Uint8Array): Uint8Array {
  if (message.length > 55) throw new RangeError('message too long for the one-block hash')
  const block = new Uint8Array(64)
  block.set(message)
  block[message.length] = 0x80
  const bits = message.length * 8
  block[62] = (bits >>> 8) & 0xff
  block[63] = bits & 0xff
  for (let i = 0; i < 16; i++) {
    W[i] = (block[i * 4] << 24) | (block[i * 4 + 1] << 16) | (block[i * 4 + 2] << 8) | block[i * 4 + 3]
  }
  for (let i = 16; i < 64; i++) {
    const a = W[i - 15]
    const b = W[i - 2]
    const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3)
    const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10)
    W[i] = (W[i - 16] + s0 + W[i - 7] + s1) | 0
  }
  let h0 = 0x6a09e667
  let h1 = 0xbb67ae85
  let h2 = 0x3c6ef372
  let h3 = 0xa54ff53a
  let h4 = 0x510e527f
  let h5 = 0x9b05688c
  let h6 = 0x1f83d9ab
  let h7 = 0x5be0cd19
  let a = h0
  let b = h1
  let c = h2
  let d = h3
  let e = h4
  let f = h5
  let g = h6
  let h = h7
  for (let i = 0; i < 64; i++) {
    const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7))
    const ch = (e & f) ^ (~e & g)
    const t1 = (h + S1 + ch + K[i] + W[i]) | 0
    const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10))
    const maj = (a & b) ^ (a & c) ^ (b & c)
    const t2 = (S0 + maj) | 0
    h = g
    g = f
    f = e
    e = (d + t1) | 0
    d = c
    c = b
    b = a
    a = (t1 + t2) | 0
  }
  h0 = (h0 + a) | 0
  h1 = (h1 + b) | 0
  h2 = (h2 + c) | 0
  h3 = (h3 + d) | 0
  h4 = (h4 + e) | 0
  h5 = (h5 + f) | 0
  h6 = (h6 + g) | 0
  h7 = (h7 + h) | 0
  const out = new Uint8Array(32)
  const view = new DataView(out.buffer)
  const words = [h0, h1, h2, h3, h4, h5, h6, h7]
  words.forEach((w, i) => view.setUint32(i * 4, w >>> 0))
  return out
}

export function leadingZeroBits(digest: Uint8Array): number {
  let bits = 0
  for (const byte of digest) {
    if (byte === 0) {
      bits += 8
      continue
    }
    return bits + Math.clz32(byte) - 24
  }
  return bits
}

const encoder = new TextEncoder()

/** Search the counter from `start`, for at most `count` tries. `null`: not in this slice. */
export function searchSlice(
  nonce: string,
  difficulty: number,
  start: number,
  count: number,
): number | null {
  for (let counter = start; counter < start + count; counter++) {
    const digest = sha256Short(encoder.encode(`${nonce}:${counter}`))
    if (leadingZeroBits(digest) >= difficulty) return counter
  }
  return null
}

const SLICE = 20_000

/** Main-thread fallback: short slices, yielding to the browser in between. */
export async function solveOnMainThread(nonce: string, difficulty: number): Promise<number> {
  for (let start = 0; ; start += SLICE) {
    const found = searchSlice(nonce, difficulty, start, SLICE)
    if (found !== null) return found
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

/** Solve a challenge in a Web Worker (falls back to time slices on the main thread). */
export function solveChallenge(challenge: PowChallenge): Promise<string> {
  const { nonce, difficulty } = challenge
  if (typeof Worker === 'undefined') {
    return solveOnMainThread(nonce, difficulty).then(String)
  }
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./pow.worker.ts', import.meta.url), { type: 'module' })
    worker.onmessage = (event: MessageEvent<{ counter: number }>) => {
      worker.terminate()
      resolve(String(event.data.counter))
    }
    worker.onerror = () => {
      worker.terminate()
      solveOnMainThread(nonce, difficulty).then((c) => resolve(String(c)), reject)
    }
    worker.postMessage({ nonce, difficulty })
  })
}

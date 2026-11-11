import { searchSlice } from './pow'

/** Worker entry: receives `{nonce, difficulty}`, answers `{counter}`. */
self.onmessage = (event: MessageEvent<{ nonce: string; difficulty: number }>) => {
  const { nonce, difficulty } = event.data
  for (let start = 0; ; start += 100_000) {
    const found = searchSlice(nonce, difficulty, start, 100_000)
    if (found !== null) {
      self.postMessage({ counter: found })
      return
    }
  }
}

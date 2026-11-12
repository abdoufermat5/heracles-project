#!/usr/bin/env node
// Bundle budget, checked against dist/ after `pnpm build`:
//   * no single JS chunk above 400 KB (minified, not gzipped);
//   * the entry, framework and ui chunks together stay under 750 KB.
// Sizes are in kB of 1000 bytes, as the build output prints them.
import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const ASSETS = join(import.meta.dirname, '..', 'dist', 'assets')
const CHUNK_LIMIT_KB = 400
const INITIAL_LIMIT_KB = 750
const INITIAL_PREFIXES = ['index-', 'framework-', 'ui-']

let files
try {
  files = readdirSync(ASSETS).filter((f) => f.endsWith('.js'))
} catch {
  console.error('check-bundle: dist/assets not found; run `pnpm build` first')
  process.exit(2)
}

const kb = (f) => statSync(join(ASSETS, f)).size / 1000
const failures = []

for (const f of files) {
  if (kb(f) > CHUNK_LIMIT_KB) {
    failures.push(`${f}: ${kb(f).toFixed(1)} kB exceeds the ${CHUNK_LIMIT_KB} kB chunk limit`)
  }
}

const initial = files.filter((f) => INITIAL_PREFIXES.some((p) => f.startsWith(p)))
const total = initial.reduce((n, f) => n + kb(f), 0)
if (total > INITIAL_LIMIT_KB) {
  failures.push(`initial JS (${initial.join(', ')}): ${total.toFixed(1)} kB exceeds ${INITIAL_LIMIT_KB} kB`)
}

console.log(`check-bundle: ${files.length} chunks, initial ${total.toFixed(1)} / ${INITIAL_LIMIT_KB} kB`)
if (failures.length > 0) {
  for (const msg of failures) console.error(`  FAIL ${msg}`)
  process.exit(1)
}

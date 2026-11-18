import i18n from '@/i18n'

const sources = import.meta.glob<string>(['/src/**/*.{ts,tsx}', '!/src/**/*.test.{ts,tsx}', '!/src/mocks/**'], {
  query: '?raw',
  import: 'default',
  eager: true,
})

describe('translation keys', () => {
  it('every literal t() key used in the sources exists in the English catalogue', () => {
    const missing: string[] = []
    for (const [file, text] of Object.entries(sources)) {
      for (const m of text.matchAll(/\bt\(\s*['"]([A-Za-z][\w-]*(?:\.[\w-]+)+)['"]/g)) {
        const key = m[1] as string
        if (!i18n.exists(key, { lng: 'en' }) && !i18n.exists(key, { lng: 'en', count: 2 })) {
          missing.push(`${file}: ${key}`)
        }
      }
    }
    expect(missing).toEqual([])
  })
})

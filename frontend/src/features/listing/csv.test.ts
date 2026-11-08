import { describe, expect, it } from 'vitest'

import { escapeCsvField } from './csv'

describe('escapeCsvField', () => {
  it('quotes separators and quotes', () => {
    expect(escapeCsvField('a,b')).toBe('"a,b"')
    expect(escapeCsvField('say "hi"')).toBe('"say ""hi"""')
    expect(escapeCsvField(['a', 'b'])).toBe('a; b')
    expect(escapeCsvField(null)).toBe('')
  })

  it.each(['=1+1', '+1', '-1', '@SUM(A1)', '\tx', '\rx'])('neutralises the formula %j', (v) => {
    expect(escapeCsvField(v).replace(/^"/, '')).toMatch(/^'/)
  })

  it('leaves ordinary values alone', () => {
    expect(escapeCsvField('uid=jdoe,ou=people')).toBe('"uid=jdoe,ou=people"')
    expect(escapeCsvField('John')).toBe('John')
  })
})

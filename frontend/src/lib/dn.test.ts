import { describe, expect, it } from 'vitest'
import { orgPath, splitDn } from './dn'

const BASE = 'dc=example,dc=com'

describe('splitDn', () => {
  it('splits RDNs and keeps escaped commas in values', () => {
    expect(splitDn('cn=Doe\\, John,ou=people,dc=example,dc=com')).toEqual([
      { attr: 'cn', value: 'Doe, John' },
      { attr: 'ou', value: 'people' },
      { attr: 'dc', value: 'example' },
      { attr: 'dc', value: 'com' },
    ])
  })
})

describe('orgPath', () => {
  it('reads top down without the base, the entry and technical containers', () => {
    expect(orgPath(`uid=adurand,ou=people,ou=Sales,ou=Paris,${BASE}`, BASE)).toEqual(['Paris', 'Sales'])
  })

  it('keeps the entry itself for departments', () => {
    expect(orgPath(`ou=Sales,ou=Paris,${BASE}`, BASE, true)).toEqual(['Paris', 'Sales'])
  })

  it('is empty for entries right under the base', () => {
    expect(orgPath(`uid=root,ou=people,${BASE}`, BASE)).toEqual([])
  })

  it('compares the base case- and space-insensitively', () => {
    expect(orgPath('cn=admins,ou=groups,ou=IT,DC=Example, DC=com', BASE)).toEqual(['IT'])
  })

  it('drops domain components when no base is known', () => {
    expect(orgPath(`cn=manager,ou=aclroles,ou=Lyon,${BASE}`)).toEqual(['Lyon'])
  })
})

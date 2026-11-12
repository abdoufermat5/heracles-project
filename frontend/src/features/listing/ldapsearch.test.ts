import { buildLdapsearch } from './ldapsearch'

describe('ldapsearch export', () => {
  it('rebuilds the view as a command without credentials', () => {
    const cmd = buildLdapsearch({
      base: 'ou=people,dc=example,dc=org',
      scope: 'sub',
      typeFilter: '(objectClass=inetOrgPerson)',
      extraFilter: '(uid=a*)',
      q: 'neil',
      searchAttrs: ['cn'],
      attrs: ['uid', 'cn'],
    })
    expect(cmd).toBe(
      "ldapsearch -H 'ldap://HOST' -D '<BIND_DN>' -W -b 'ou=people,dc=example,dc=org' -s sub " +
        "'(&(objectClass=inetOrgPerson)(uid=a*)(cn=*neil*))' 'uid' 'cn'",
    )
  })
})

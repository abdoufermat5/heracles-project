/**
 * Turning distinguished names into something people read.
 *
 * `uid=adurand,ou=people,ou=Sales,ou=Paris,dc=example,dc=com` under the base
 * `dc=example,dc=com` becomes ["Paris", "Sales"]: the organisational path, top
 * down, without the entry itself, the base and technical containers.
 */

/** Containers that hold objects of one type; they mean nothing to a person. */
const TECHNICAL_CONTAINERS = new Set([
  'people',
  'groups',
  'aclroles',
  'roles',
  'systems',
  'dns',
  'sudoers',
  'devices',
  'apps',
])

export interface Rdn {
  attr: string
  value: string
}

/** Split a DN into its RDNs, honouring backslash escapes (`cn=Doe\, John`). */
export function splitDn(dn: string): Rdn[] {
  const parts: string[] = []
  let cur = ''
  for (let i = 0; i < dn.length; i++) {
    const ch = dn[i]
    if (ch === '\\' && i + 1 < dn.length) {
      cur += ch + dn[i + 1]
      i++
    } else if (ch === ',') {
      parts.push(cur)
      cur = ''
    } else {
      cur += ch
    }
  }
  if (cur) parts.push(cur)
  return parts
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => {
      const eq = p.indexOf('=')
      const raw = eq >= 0 ? p.slice(eq + 1) : p
      return {
        attr: eq >= 0 ? p.slice(0, eq).trim().toLowerCase() : '',
        value: raw.trim().replace(/\\(.)/g, '$1'),
      }
    })
}

function sameDn(a: string, b: string): boolean {
  return a.replace(/\s*,\s*/g, ',').toLowerCase() === b.replace(/\s*,\s*/g, ',').toLowerCase()
}

/**
 * Organisational path of an entry, top down (["Paris", "Sales"]).
 *
 * `includeSelf` keeps the entry's own name (for departments themselves).
 */
export function orgPath(dn: string, baseDn?: string, includeSelf = false): string[] {
  let rdns = splitDn(dn)
  if (baseDn) {
    const base = splitDn(baseDn)
    const tail = rdns.slice(rdns.length - base.length)
    if (
      base.length > 0 &&
      tail.length === base.length &&
      sameDn(tail.map((r) => `${r.attr}=${r.value}`).join(','), baseDn)
    ) {
      rdns = rdns.slice(0, rdns.length - base.length)
    }
  } else {
    rdns = rdns.filter((r) => r.attr !== 'dc')
  }
  if (!includeSelf) rdns = rdns.slice(1)
  return rdns
    .filter((r) => !(r.attr === 'ou' && TECHNICAL_CONTAINERS.has(r.value.toLowerCase())))
    .map((r) => r.value)
    .reverse()
}

/** Shell-quotes a value with single quotes. */
export function shellQuote(v: string): string {
  return `'${v.replace(/'/g, `'\\''`)}'`
}

export interface LdapsearchView {
  base: string
  scope: 'one' | 'sub'
  /** LDAP filter selecting the type (from the type descriptor), if known. */
  typeFilter?: string
  /** The raw filter typed in the toolbar. */
  extraFilter?: string
  /** Free-text search: matched as substring against `searchAttrs`. */
  q?: string
  searchAttrs?: string[]
  /** Attributes to return. */
  attrs: string[]
}

/** Escapes a value for use in an LDAP filter assertion. */
function escapeValue(v: string): string {
  return v.replace(/[\\*()\0]/g, (c) => `\\${c.charCodeAt(0).toString(16).padStart(2, '0')}`)
}

/** The filter the current listing view stands for. */
export function viewFilter(v: LdapsearchView): string {
  const parts: string[] = []
  if (v.typeFilter) parts.push(v.typeFilter)
  if (v.extraFilter) parts.push(v.extraFilter)
  const words = (v.q ?? '').split(/\s+/).filter(Boolean)
  const attrs = v.searchAttrs ?? v.attrs
  for (const w of words) {
    const clauses = attrs.map((a) => `(${a}=*${escapeValue(w)}*)`)
    if (clauses.length > 0) parts.push(clauses.length === 1 ? clauses.join('') : `(|${clauses.join('')})`)
  }
  if (parts.length === 0) return '(objectClass=*)'
  return parts.length === 1 ? parts.join('') : `(&${parts.join('')})`
}

/**
 * `ldapsearch` command reproducing a listing view. No credentials: the server, bind DN
 * and the password prompt are left for the operator (`-H` / `-D` / `-W`).
 */
export function buildLdapsearch(v: LdapsearchView, uri = 'ldap://HOST'): string {
  return [
    'ldapsearch',
    '-H',
    shellQuote(uri),
    '-D',
    shellQuote('<BIND_DN>'),
    '-W',
    '-b',
    shellQuote(v.base),
    '-s',
    v.scope === 'sub' ? 'sub' : 'one',
    shellQuote(viewFilter(v)),
    ...v.attrs.map(shellQuote),
  ].join(' ')
}

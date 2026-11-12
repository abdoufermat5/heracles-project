/** Minimal RFC 4515 filter evaluator for the mock listing (`filter` query parameter). */

type Node =
  | { op: '&'; kids: Node[] }
  | { op: '|'; kids: Node[] }
  | { op: '!'; kid: Node }
  | { op: '='; attr: string; value: string }

export class FilterSyntaxError extends Error {}

function parseNode(s: string, start: number): [Node, number] {
  let i = start
  if (s[i] !== '(') throw new FilterSyntaxError('expected "("')
  i++
  const c = s[i]
  if (c === '&' || c === '|') {
    const kids: Node[] = []
    i++
    while (s[i] === '(') {
      const [k, next] = parseNode(s, i)
      kids.push(k)
      i = next
    }
    if (s[i] !== ')' || kids.length === 0) throw new FilterSyntaxError('expected ")"')
    return [c === '&' ? { op: '&', kids } : { op: '|', kids }, i + 1]
  }
  if (c === '!') {
    const [kid, next] = parseNode(s, i + 1)
    if (s[next] !== ')') throw new FilterSyntaxError('expected ")"')
    return [{ op: '!', kid }, next + 1]
  }
  const end = s.indexOf(')', i)
  const eq = s.indexOf('=', i)
  if (end < 0 || eq < 0 || eq > end) throw new FilterSyntaxError('malformed item')
  return [{ op: '=', attr: s.slice(i, eq), value: s.slice(eq + 1, end) }, end + 1]
}

export function parseLdapFilter(text: string): Node {
  const t = text.trim()
  const [node, end] = parseNode(t, 0)
  if (end !== t.length) throw new FilterSyntaxError('trailing characters')
  return node
}

export function attributesOf(node: Node): string[] {
  if (node.op === '=') return [node.attr]
  if (node.op === '!') return attributesOf(node.kid)
  return node.kids.flatMap(attributesOf)
}

export function ldapMatches(node: Node, get: (attr: string) => string[]): boolean {
  if (node.op === '&') return node.kids.every((k) => ldapMatches(k, get))
  if (node.op === '|') return node.kids.some((k) => ldapMatches(k, get))
  if (node.op === '!') return !ldapMatches(node.kid, get)
  const values = get(node.attr)
  if (node.value === '*') return values.length > 0
  const source = node.value
    .split('*')
    .map((p) => p.replace(/[.+?^${}()|[\]\\]/g, '\\$&'))
    .join('.*')
  const re = new RegExp(`^${source}$`, 'i')
  return values.some((v) => re.test(v))
}

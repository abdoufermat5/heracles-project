import type {
  AttributeDescriptor,
  ObjectDetail,
  TabAcl,
  TabDescriptor,
  TypeDescriptor,
  Values,
} from '@/api/types'

export type AttrRight = 'hidden' | 'r' | 'rw'

/** Effective right on one attribute, from the object response `acl` block. */
export function attrRight(
  acl: ObjectDetail['acl'] | undefined,
  tab: string,
  attr: AttributeDescriptor,
): AttrRight {
  if (attr.kind === 'display') return 'r'
  let right: AttrRight = 'rw'
  const tabAcl: TabAcl | undefined = acl?.[tab]
  if (tabAcl) {
    const r = tabAcl.attributes[attr.name]
    if (r === undefined) right = tabAcl.object.includes('m') ? 'rw' : 'r'
    else if (r === '') right = 'hidden'
    else right = r.includes('w') ? 'rw' : 'r'
  }
  if (attr.readonly && right === 'rw') right = 'r'
  return right
}

export function isEmpty(v: unknown): boolean {
  return (
    v === undefined ||
    v === null ||
    v === '' ||
    (Array.isArray(v) && v.length === 0) ||
    (typeof v === 'object' && !Array.isArray(v) && v !== null && Object.keys(v).length === 0)
  )
}

export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (isEmpty(a) && isEmpty(b)) return true
  if (typeof a !== typeof b || a === null || b === null) return false
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((x, i) => deepEqual(x, b[i]))
  }
  if (typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a as object)
    const kb = Object.keys(b as object)
    const keys = new Set([...ka, ...kb])
    for (const k of keys) {
      if (!deepEqual((a as Values)[k], (b as Values)[k])) return false
    }
    return true
  }
  return false
}

/** Default value for an attribute when creating an object (or adding a list item). */
export function defaultValue(a: AttributeDescriptor): unknown {
  if (a.default !== undefined && a.default !== null) return structuredClone(a.default)
  if (a.kind === 'composite') {
    return Object.fromEntries((a.fields ?? []).map((f) => [f.name, defaultValue(f)]))
  }
  if (a.kind === 'list' || a.kind === 'multiselect' || (a.multivalued && a.kind !== 'password'))
    return []
  if (a.kind === 'boolean') return false
  if (a.kind === 'password') return null
  return null
}

export type FormValues = Record<string, Values>

export function allAttributes(tab: TabDescriptor): AttributeDescriptor[] {
  return tab.sections.flatMap((s) => s.attributes)
}

/** Form values from an object response (missing attrs get defaults of "empty"). */
export function valuesFromDetail(desc: TypeDescriptor, detail: ObjectDetail | null): FormValues {
  const out: FormValues = {}
  for (const tab of desc.tabs) {
    const src = detail?.tabs[tab.name]?.values ?? {}
    const vals: Values = {}
    for (const a of allAttributes(tab)) {
      const v = src[a.name]
      if (v !== undefined) vals[a.name] = structuredClone(v)
      else vals[a.name] = detail ? emptyValue(a) : defaultValue(a)
    }
    // keep unknown attributes (e.g. hidden extras) so they are not lost
    for (const [k, v] of Object.entries(src)) if (!(k in vals)) vals[k] = v
    out[tab.name] = vals
  }
  return out
}

function emptyValue(a: AttributeDescriptor): unknown {
  if (a.kind === 'list' || a.kind === 'multiselect' || (a.multivalued && a.kind !== 'password'))
    return []
  if (a.kind === 'boolean') return false
  return null
}

export function activeFromDetail(
  desc: TypeDescriptor,
  detail: ObjectDetail | null,
): Record<string, boolean> {
  return Object.fromEntries(
    desc.tabs.map((t) => [t.name, detail ? (detail.tabs[t.name]?.active ?? false) : !t.optional]),
  )
}

export interface TabChange {
  active: boolean
  values: Values
}

/**
 * Build the PATCH body: only tabs whose activation or values changed, and only
 * the changed attributes in each. Password `null` (untouched) is never sent.
 */
export function computeChanges(
  desc: TypeDescriptor,
  initial: FormValues,
  initialActive: Record<string, boolean>,
  current: FormValues,
  active: Record<string, boolean>,
  skip: ReadonlySet<string> = new Set(),
): Record<string, TabChange> {
  const out: Record<string, TabChange> = {}
  for (const tab of desc.tabs) {
    const wasActive = initialActive[tab.name] ?? false
    const isActive = active[tab.name] ?? false
    if (!isActive) {
      if (wasActive) out[tab.name] = { active: false, values: {} }
      continue
    }
    const values: Values = {}
    for (const a of allAttributes(tab)) {
      if (skip.has(`${tab.name}.${a.name}`)) continue
      if (a.kind === 'display' || a.kind === 'hidden') continue
      const cur = current[tab.name]?.[a.name]
      if (a.kind === 'password') {
        if (typeof cur === 'string' && cur !== '') values[a.name] = cur
        continue
      }
      const init = wasActive ? initial[tab.name]?.[a.name] : undefined
      if (!wasActive || !deepEqual(cur, init)) {
        if (!wasActive && isEmpty(cur) && a.kind !== 'boolean') continue
        values[a.name] = isEmpty(cur) && a.kind !== 'boolean' ? emptyForSend(a) : cur
      }
    }
    if (!wasActive || Object.keys(values).length > 0) out[tab.name] = { active: true, values }
  }
  return out
}

function emptyForSend(a: AttributeDescriptor): unknown {
  return a.kind === 'list' || a.kind === 'multiselect' || a.multivalued ? [] : null
}

/** Full values per active tab for creation (empty values omitted). */
export function buildCreateTabs(
  desc: TypeDescriptor,
  current: FormValues,
  active: Record<string, boolean>,
): Record<string, TabChange> {
  const out: Record<string, TabChange> = {}
  for (const tab of desc.tabs) {
    if (!active[tab.name]) continue
    const values: Values = {}
    for (const a of allAttributes(tab)) {
      if (a.kind === 'display') continue
      const v = current[tab.name]?.[a.name]
      if (a.kind === 'password') {
        if (typeof v === 'string' && v) values[a.name] = v
        continue
      }
      if (isEmpty(v) && a.kind !== 'boolean') continue
      values[a.name] = v
    }
    out[tab.name] = { active: true, values }
  }
  return out
}

/** Split "tab.attr.rest" into its parts. */
export function splitFieldKey(key: string): { tab: string; attr: string; rest: string } | null {
  const [tab, attr, ...rest] = key.split('.')
  if (!tab || !attr) return null
  return { tab, attr, rest: rest.join('.') }
}

export function nameValue(desc: TypeDescriptor, detail: ObjectDetail): string {
  for (const tab of Object.values(detail.tabs)) {
    const v = tab.values[desc.name_attr]
    if (typeof v === 'string' && v) return v
  }
  return rdnValue(detail.dn)
}

export function rdnValue(dn: string): string {
  const first = dn.split(',')[0] ?? dn
  const idx = first.indexOf('=')
  return idx >= 0 ? first.slice(idx + 1) : first
}

export function parentDn(dn: string): string {
  const idx = dn.indexOf(',')
  return idx >= 0 ? dn.slice(idx + 1) : dn
}

/** Department DN that contains an object DN (skips type containers like ou=people). */
export function departmentOf(dn: string, knownDepartments: ReadonlySet<string>): string | null {
  let cur = parentDn(dn)
  while (cur) {
    if (knownDepartments.has(cur.toLowerCase())) return cur
    const next = parentDn(cur)
    if (next === cur) break
    cur = next
  }
  return null
}

export interface FieldDiff {
  tab: string
  tabLabel: string
  attr: string
  attrLabel: string
  oldValue: unknown
  newValue: unknown
}

export function listFieldDiffs(
  desc: TypeDescriptor,
  baseline: FormValues,
  current: FormValues,
  active: Record<string, boolean>,
): FieldDiff[] {
  const diffs: FieldDiff[] = []
  for (const tab of desc.tabs) {
    if (!active[tab.name]) continue
    for (const a of allAttributes(tab)) {
      if (a.kind === 'display' || a.kind === 'hidden') continue
      const oldVal = baseline[tab.name]?.[a.name]
      const newVal = current[tab.name]?.[a.name]
      if (!deepEqual(oldVal, newVal)) {
        diffs.push({
          tab: tab.name,
          tabLabel: tab.label,
          attr: a.name,
          attrLabel: a.label,
          oldValue: oldVal,
          newValue: newVal,
        })
      }
    }
  }
  return diffs
}

export function objectToLdif(
  desc: TypeDescriptor,
  dn: string,
  values: FormValues,
  active: Record<string, boolean>,
): string {
  const lines: string[] = [`dn: ${dn}`, 'objectClass: top', `objectClass: ${desc.name}`]
  for (const tab of desc.tabs) {
    if (!active[tab.name]) continue
    for (const a of allAttributes(tab)) {
      if (a.kind === 'display' || a.kind === 'hidden') continue
      const v = values[tab.name]?.[a.name]
      if (v === null || v === undefined || v === '') continue
      if (Array.isArray(v)) {
        for (const item of v) {
          if (item !== null && item !== undefined && item !== '') {
            lines.push(`${a.name}: ${String(item)}`)
          }
        }
      } else if (typeof v === 'object') {
        lines.push(`${a.name}: ${JSON.stringify(v)}`)
      } else {
        lines.push(`${a.name}: ${String(v)}`)
      }
    }
  }
  return lines.join('\n') + '\n'
}

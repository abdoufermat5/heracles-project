import type {
  AttributeDescriptor,
  Directory,
  LockInfo,
  Me,
  ObjectDetail,
  Snapshot,
  TabAcl,
  TabState,
  TreeNode,
  TypeDescriptor,
  Values,
} from '@/api/types'
import { typeDescriptors, typeRdn } from './typeDefs'

export const BASE_DN = 'dc=example,dc=com'

interface Rec {
  dn: string
  type: string
  tabs: Record<string, TabState>
  accountLocked: boolean
}

// Small deterministic PRNG so the dataset is stable across reloads.
function rng(seed: number): () => number {
  let s = seed
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296
    return s / 4294967296
  }
}

const FIRST = ['Alice', 'Bruno', 'Chloé', 'David', 'Emma', 'Farid', 'Grace', 'Hugo', 'Inès', 'Jules', 'Katia', 'Louis', 'Mina', 'Noah', 'Olga', 'Paul', 'Quentin', 'Rosa', 'Samir', 'Tara', 'Ulysse', 'Vera', 'William', 'Xavier', 'Yara', 'Zoé']
const LAST = ['Martin', 'Bernard', 'Dubois', 'Thomas', 'Robert', 'Richard', 'Petit', 'Durand', 'Leroy', 'Moreau', 'Simon', 'Laurent', 'Lefebvre', 'Michel', 'Garcia', 'David', 'Bertrand', 'Roux', 'Vincent', 'Fournier', 'Morel', 'Girard', 'Andre', 'Mercier', 'Dupont', 'Lambert']
const TYPES = ['employee', 'employee', 'employee', 'contractor', 'intern']

function ascii(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
}

export const departments = [
  { dn: `ou=Paris,${BASE_DN}`, ou: 'Paris' },
  { dn: `ou=Lyon,${BASE_DN}`, ou: 'Lyon' },
  { dn: `ou=Engineering,ou=Paris,${BASE_DN}`, ou: 'Engineering' },
  { dn: `ou=Sales,ou=Paris,${BASE_DN}`, ou: 'Sales' },
  { dn: `ou=Support,ou=Lyon,${BASE_DN}`, ou: 'Support' },
]

export const USER_COUNT = 200

/** A snapshot as the mock API stores it. */
export type MockSnapshot = Snapshot & { dn: string; type: string }

/** An object template as the mock API stores it. */
export interface MockTemplate {
  dn: string
  name: string
  type: string
  base: string
  tabs: Record<string, { active: boolean; values: Record<string, string | string[]> }>
}

/** What the mock API reports as a user's registered second factors. */
export interface MockSecondFactors {
  totp: boolean
  security_keys: { id: string; label: string }[]
  recovery_codes: number
}

class Db {
  records = new Map<string, Rec>()
  locks = new Map<string, LockInfo>()
  snapshots = new Map<string, MockSnapshot>()
  session: { user: string | null; pending: string | null } = { user: null, pending: null }
  // --- P3 objects ---
  templates = new Map<string, MockTemplate>()
  /** Stored tab values of each snapshot (so a deleted object can be restored). */
  snapshotTabs = new Map<string, Record<string, TabState>>()
  /** Second factors per user (lower-cased DN), as the administrator view lists them. */
  secondFactors = new Map<string, MockSecondFactors>()
  // --- end P3 objects ---
  /** Registered WebAuthn keys of the signed-in mock user. */
  securityKeys: { id: string; label: string; sign_count: number }[] = []
  /** Authenticator-app state of the signed-in mock user. */
  totp = { enabled: false, recoveryCodes: 0, pending: false }
  /** Open sessions of the signed-in mock user (the first one is the current one). */
  sessions: { id: string; user_agent: string; ip: string; created_at: number; last_seen: number; current: boolean }[] = []
  /** False once the mock session needs a password confirmation for key changes. */
  reauthFresh = true
  csrf = 'mock-csrf-token'
  nextId = 1000
  recoveryTokens = new Set<string>(['valid-token'])

  constructor() {
    this.seed()
  }

  reset(): void {
    this.records.clear()
    this.locks.clear()
    this.snapshots.clear()
    this.templates.clear()
    this.secondFactors.clear()
    this.snapshotTabs.clear()
    this.securityKeys = []
    this.totp = { enabled: false, recoveryCodes: 0, pending: false }
    this.reauthFresh = true
    this.sessions = []
    this.session = { user: null, pending: null }
    this.seed()
  }

  private put(type: string, dn: string, tabs: Record<string, TabState>, accountLocked = false) {
    this.records.set(dn.toLowerCase(), { dn, type, tabs, accountLocked })
  }

  private seed(): void {
    const rand = rng(42)
    const userDns: string[] = []
    const leafDepts = [departments[2], departments[3], departments[4], departments[0], departments[1]]

    for (const d of departments) {
      this.put('department', d.dn, {
        main: {
          active: true,
          values: {
            ou: d.ou,
            description: `${d.ou} department`,
            base: d.dn.slice(d.dn.indexOf(',') + 1),
          },
        },
      })
    }

    for (let i = 0; i < USER_COUNT - 1; i++) {
      const given = FIRST[Math.floor(rand() * FIRST.length)] ?? 'Alex'
      const sn = LAST[Math.floor(rand() * LAST.length)] ?? 'Doe'
      const uid = `${ascii(given)[0] ?? 'x'}${ascii(sn)}${i < 26 ? '' : i}`
      const dept = leafDepts[i % leafDepts.length] ?? departments[0]
      if (!dept) continue
      const dn = `uid=${uid},ou=people,${dept.dn}`
      userDns.push(dn)
      const hasPosix = i % 3 === 0
      this.put(
        'user',
        dn,
        {
          main: {
            active: true,
            values: {
              givenName: given,
              sn,
              cn: `${given} ${sn}`,
              uid,
              base: dept.dn,
              mail: `${uid}@example.com`,
              telephoneNumber: i % 4 === 0 ? [`+33 1 23 45 67 ${String(i % 100).padStart(2, '0')}`] : [],
              employeeType: TYPES[i % TYPES.length],
              preferredLanguage: i % 5 === 0 ? 'fr' : 'en',
              forcePasswordChange: i % 19 === 3,
              passwordExpiry: i % 23 === 2 ? '2026-01-01T00:00:00Z' : null,
              userPassword: null,
              jpegPhoto: null,
              description: '',
              internalId: `EMP-${10000 + i}`,
            },
          },
          posix: hasPosix
            ? {
                active: true,
                values: {
                  uidNumber: 10000 + i,
                  gidNumber: 10000,
                  homeDirectory: `/home/${uid}`,
                  loginShell: '/bin/bash',
                  diskQuotaGb: 5,
                  groups: ['staff'],
                },
              }
            : { active: false, values: {} },
        },
        i % 17 === 5,
      )
    }

    // Seed dedicated realistic employee user
    const empDept = departments[2] ?? departments[0]
    const empDeptDn = empDept ? empDept.dn : BASE_DN
    const empDn = `uid=employee,ou=people,${empDeptDn}`
    userDns.push(empDn)
    this.put(
      'user',
      empDn,
      {
        main: {
          active: true,
          values: {
            givenName: 'Emma',
            sn: 'Employee',
            cn: 'Emma Employee',
            uid: 'employee',
            base: empDeptDn,
            mail: 'emma.employee@example.com',
            telephoneNumber: ['+33 1 40 50 60 70'],
            employeeType: 'employee',
            preferredLanguage: 'en',
            forcePasswordChange: false,
            userPassword: null,
            jpegPhoto: null,
            description: 'Senior Software Engineer',
            internalId: 'EMP-0042',
          },
        },
        posix: {
          active: true,
          values: {
            uidNumber: 10500,
            gidNumber: 10000,
            homeDirectory: '/home/employee',
            loginShell: '/bin/bash',
            diskQuotaGb: 10,
            groups: ['staff', 'developers'],
          },
        },
      },
      false,
    )

    // A user whose edit lock is held by somebody else (to exercise the 409 dialog).
    const lockedDn = userDns[1]
    if (lockedDn) {
      this.locks.set(lockedDn.toLowerCase(), { user: 'bob.admin', since: '2026-01-15T09:30:00Z' })
    }

    // A user with every kind of second factor (administrator view and reset).
    const factorDn = userDns[2]
    if (factorDn) {
      this.secondFactors.set(factorDn.toLowerCase(), {
        totp: true,
        security_keys: [
          { id: 'key-desk', label: 'Desk key' },
          { id: 'key-phone', label: '' },
        ],
        recovery_codes: 6,
      })
    }

    const groups = ['admins', 'staff', 'developers', 'sales', 'support', 'interns']
    groups.forEach((g, i) => {
      const dept = departments[0]
      if (!dept) return
      const members = userDns.slice(i * 3, i * 3 + 6)
      if (g === 'staff' || g === 'developers') members.push(empDn)
      this.put('group', `cn=${g},ou=groups,${dept.dn}`, {
        main: {
          active: true,
          values: {
            base: dept.dn,
            cn: g,
            description: `${g} group`,
            member: members,
          },
        },
      })
    })
    ;['hr-manager', 'it-operator', 'auditor'].forEach((r, i) => {
      this.put('role', `cn=${r},ou=roles,${BASE_DN}`, {
        main: {
          active: true,
          values: { base: BASE_DN, cn: r, description: `${r} role`, roleOccupant: userDns.slice(i, i + 2) },
        },
      })
    })
    ;['example.com', 'example.org', 'corp.example.net', 'lab.example.com'].forEach((z, i) => {
      this.put('dns_zone', `zoneName=${z},ou=dns,${BASE_DN}`, {
        main: {
          active: true,
          values: {
            base: BASE_DN,
            zoneName: z,
            serial: 2026010100 + i,
            description: `Zone ${z}`,
            soa: {
              primaryNs: `ns1.${z}`,
              adminEmail: `hostmaster@${z}`,
              refresh: 3600,
              retry: 600,
              expire: 1209600,
              minimum: 300,
            },
            nameservers: [`ns1.${z}`, `ns2.${z}`],
            records: [
              { name: '@', type: 'A', ttl: 3600, value: '192.0.2.10' },
              { name: 'www', type: 'CNAME', ttl: 3600, value: `${z}.` },
              { name: '@', type: 'MX', ttl: 3600, value: `10 mail.${z}.` },
            ],
          },
        },
      })
    })
  }

  // ── lookups ─────────────────────────────────────────────────────────────

  descriptor(type: string): TypeDescriptor | undefined {
    return typeDescriptors.find((t) => t.name === type)
  }

  get(dn: string): Rec | undefined {
    return this.records.get(dn.toLowerCase())
  }

  all(type: string): Rec[] {
    return [...this.records.values()].filter((r) => r.type === type)
  }

  tree(): TreeNode[] {
    const nodes = new Map<string, TreeNode>()
    const root: TreeNode = { dn: BASE_DN, label: 'Example', kind: 'dc', children: [] }
    nodes.set(BASE_DN.toLowerCase(), root)
    const depts = this.all('department').sort((a, b) => a.dn.length - b.dn.length)
    for (const d of depts) {
      const parentDn = d.dn.slice(d.dn.indexOf(',') + 1)
      const parent = nodes.get(parentDn.toLowerCase()) ?? root
      const node: TreeNode = {
        dn: d.dn,
        label: String(d.tabs.main?.values.ou ?? d.dn),
        kind: 'ou',
        children: [],
      }
      nodes.set(d.dn.toLowerCase(), node)
      parent.children.push(node)
    }
    return [root]
  }

  directories(): Directory[] {
    return [
      { id: 'main', label: 'Main directory' },
      { id: 'lab', label: 'Lab directory' },
    ]
  }

  // ── identity ────────────────────────────────────────────────────────────

  me(): Me | null {
    const u = this.session.user
    if (!u) return null
    if (u === 'employee') {
      const deptDn = `ou=Engineering,ou=Paris,${BASE_DN}`
      return {
        dn: `uid=employee,ou=people,${deptDn}`,
        uid: 'employee',
        display_name: 'Emma Employee',
        avatar_url: null,
        is_admin: false,
        directory: 'main',
        base: BASE_DN,
      }
    }
    const isAdmin = u !== 'viewer'
    return {
      dn: `uid=${u},ou=people,${BASE_DN}`,
      uid: u,
      display_name: isAdmin ? 'Ada Admin' : 'Vic Viewer',
      avatar_url: null,
      is_admin: isAdmin,
      directory: 'main',
      base: BASE_DN,
    }
  }

  isReadOnlySession(): boolean {
    return this.session.user === 'viewer'
  }

  // ── acl ─────────────────────────────────────────────────────────────────

  acl(rec: Rec, desc: TypeDescriptor): Record<string, TabAcl> {
    const out: Record<string, TabAcl> = {}
    const ro = this.isReadOnlySession()
    const myDn = this.me()?.dn.toLowerCase()
    const isSelf = this.session.user === 'employee' && rec.dn.toLowerCase() === myDn
    for (const tab of desc.tabs) {
      const attrs: Record<string, string> = {}
      for (const sec of tab.sections) {
        for (const a of sec.attributes) {
          if (a.kind === 'display') {
            attrs[a.name] = 'r'
          } else if (isSelf) {
            if (['telephoneNumber', 'description', 'preferredLanguage', 'jpegPhoto', 'userPassword'].includes(a.name)) {
              attrs[a.name] = 'rw'
            } else {
              attrs[a.name] = 'r'
            }
          } else if (ro) {
            attrs[a.name] = a.name === 'userPassword' ? '' : 'r'
          } else if (a.name === desc.main_attr) {
            attrs[a.name] = 'r'
          } else if (tab.name === 'main' && a.name === 'employeeType' && rec.type === 'user') {
            attrs[a.name] = 'r'
          } else {
            attrs[a.name] = 'rw'
          }
        }
      }
      out[tab.name] = { object: isSelf ? 'rw' : ro ? 'r' : 'rwcdm', attributes: attrs }
    }
    return out
  }

  detail(rec: Rec): ObjectDetail {
    const desc = this.descriptor(rec.type)
    if (!desc) throw new Error(`unknown type ${rec.type}`)
    const tabs: Record<string, TabState> = {}
    for (const t of desc.tabs) {
      const st = rec.tabs[t.name] ?? { active: false, values: {} }
      tabs[t.name] = { active: st.active, values: { ...st.values } }
    }
    return { dn: rec.dn, type: rec.type, tabs, acl: this.acl(rec, desc) }
  }

  // ── validation ──────────────────────────────────────────────────────────

  validate(desc: TypeDescriptor, tabs: Record<string, TabState>, selfDn?: string): Record<string, string> {
    const errors: Record<string, string> = {}
    for (const tab of desc.tabs) {
      const st = tabs[tab.name]
      if (!st?.active) continue
      for (const sec of tab.sections) {
        for (const a of sec.attributes) {
          this.validateAttr(a, st.values[a.name], `${tab.name}.${a.name}`, errors)
        }
      }
    }
    const mainVal = tabs.main?.values[desc.main_attr]
    if (typeof mainVal === 'string' && mainVal) {
      const dup = this.all(desc.name).find(
        (r) =>
          r.dn.toLowerCase() !== selfDn?.toLowerCase() &&
          String(r.tabs.main?.values[desc.main_attr] ?? '').toLowerCase() === mainVal.toLowerCase(),
      )
      if (dup) errors[`main.${desc.main_attr}`] = 'This value is already in use'
    }
    return errors
  }

  private validateAttr(a: AttributeDescriptor, v: unknown, key: string, errors: Record<string, string>) {
    if (a.kind === 'display' || a.kind === 'hidden') return
    const empty = v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0)
    if (empty) {
      if (a.required && a.kind !== 'password') errors[key] = 'This field is required'
      return
    }
    if (a.kind === 'composite' && a.fields && typeof v === 'object' && !Array.isArray(v)) {
      for (const f of a.fields) {
        this.validateAttr(f, (v as Values)[f.name], `${key}.${f.name}`, errors)
      }
      return
    }
    if (a.kind === 'list' && a.item && Array.isArray(v)) {
      const itemDesc = a.item
      v.forEach((item, i) => this.validateAttr({ ...itemDesc, required: true }, item, `${key}.${i}`, errors))
      return
    }
    if (Array.isArray(v) && a.multivalued && a.kind !== 'multiselect') {
      v.forEach((item, i) => this.validateAttr({ ...a, multivalued: false }, item, `${key}.${i}`, errors))
      return
    }
    const c = a.constraints
    if (typeof v === 'string') {
      if (c?.pattern && !new RegExp(c.pattern).test(v)) errors[key] = 'Invalid format'
      else if (c?.min_length && v.length < c.min_length)
        errors[key] = `Must be at least ${c.min_length} characters`
      else if (c?.max_length && v.length > c.max_length)
        errors[key] = `Must be at most ${c.max_length} characters`
      else if (a.kind === 'email' && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)) errors[key] = 'Invalid email address'
    }
    if (typeof v === 'number') {
      if (c?.min !== undefined && v < c.min) errors[key] = `Must be at least ${c.min}`
      else if (c?.max !== undefined && v > c.max) errors[key] = `Must be at most ${c.max}`
    }
  }

  // ── mutations ───────────────────────────────────────────────────────────

  computeDerived(type: string, tabs: Record<string, TabState>): void {
    const main = tabs.main
    if (type === 'user' && main) {
      main.values.cn = `${String(main.values.givenName ?? '')} ${String(main.values.sn ?? '')}`.trim()
    }
  }

  dnFor(desc: TypeDescriptor, base: string, tabs: Record<string, TabState>): string {
    const val = String(tabs.main?.values[desc.main_attr] ?? '')
    const rdn = typeRdn[desc.name]
    const container = rdn ? `${rdn},` : ''
    return `${desc.main_attr}=${val},${container}${base}`
  }

  create(type: string, base: string, tabs: Record<string, TabState>): Rec {
    const desc = this.descriptor(type)
    if (!desc) throw new Error('unknown type')
    this.computeDerived(type, tabs)
    const dn = this.dnFor(desc, base, tabs)
    const clean: Record<string, TabState> = {}
    for (const t of desc.tabs) {
      const st = tabs[t.name]
      clean[t.name] = st ? { active: st.active, values: { ...st.values } } : { active: false, values: {} }
    }
    const main = clean.main
    if (main) {
      main.values.base = base
      if (type === 'dns_zone') main.values.serial = 2026010100
    }
    this.put(type, dn, clean)
    const rec = this.get(dn)
    if (!rec) throw new Error('create failed')
    return rec
  }

  patch(rec: Rec, tabs: Record<string, { active: boolean; values: Values }>): void {
    const desc = this.descriptor(rec.type)
    if (!desc) return
    for (const [name, change] of Object.entries(tabs)) {
      const tab = desc.tabs.find((t) => t.name === name)
      if (!tab) continue
      const cur = rec.tabs[name] ?? { active: false, values: {} }
      if (!change.active) {
        if (tab.optional) rec.tabs[name] = { active: false, values: {} }
        continue
      }
      const next: Values = { ...cur.values }
      for (const [k, v] of Object.entries(change.values)) {
        if (k === 'userPassword') {
          if (v === null) continue
          next[k] = null // passwords are never echoed back
          continue
        }
        next[k] = v
      }
      rec.tabs[name] = { active: true, values: next }
    }
    this.computeDerived(rec.type, rec.tabs)
  }

  remove(dn: string): void {
    this.records.delete(dn.toLowerCase())
    this.locks.delete(dn.toLowerCase())
  }

  move(rec: Rec, newBase: string): string {
    const desc = this.descriptor(rec.type)
    if (!desc) return rec.dn
    const newDn = this.dnFor(desc, newBase, rec.tabs)
    this.records.delete(rec.dn.toLowerCase())
    const old = rec.dn
    rec.dn = newDn
    const main = rec.tabs.main
    if (main) main.values.base = newBase
    this.records.set(newDn.toLowerCase(), rec)
    const lock = this.locks.get(old.toLowerCase())
    if (lock) {
      this.locks.delete(old.toLowerCase())
      this.locks.set(newDn.toLowerCase(), lock)
    }
    return newDn
  }

  newId(): string {
    return String(this.nextId++)
  }
}

export const db = new Db()

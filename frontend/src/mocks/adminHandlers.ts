import { http, HttpResponse, type HttpHandler } from 'msw'
import type {
  AclRole,
  Assignment,
  Capabilities,
  Catalog,
  ConfigField,
  ConfigKind,
  ConfigValue,
  HealthCheck,
  Hook,
  PluginInfo,
  RightsReport,
  TaskRow,
} from '@/features/admin/types'
import { BASE_DN, db, departments } from './db'

const A = '/api/v2/admin'

const dn = (p: string | readonly string[] | undefined): string =>
  decodeURIComponent(Array.isArray(p) ? (p[0] ?? '') : String(p ?? ''))

function err(status: number, code: string, message: string, fields?: Record<string, string>) {
  return HttpResponse.json({ error: { code, message, ...(fields ? { fields } : {}) } }, { status })
}

// ── state ───────────────────────────────────────────────────────────────────

const ROLES_DN = `ou=aclroles,${BASE_DN}`

const catalog: Catalog = {
  all: 'all',
  categories: [
    {
      category: 'user',
      label: 'Users',
      wildcard: 'user/0',
      objects: [
        {
          key: 'user/user',
          label: 'User account',
          type: 'user',
          attributes: [
            { name: 'cn', label: 'Full name' },
            { name: 'sn', label: 'Surname' },
            { name: 'givenName', label: 'First name' },
            { name: 'uid', label: 'Login' },
            { name: 'mail', label: 'Email' },
            { name: 'telephoneNumber', label: 'Phone' },
            { name: 'employeeType', label: 'Contract type' },
            { name: 'userPassword', label: 'Password' },
          ],
        },
        {
          key: 'user/posixAccount',
          label: 'Unix account',
          type: 'user',
          attributes: [
            { name: 'uidNumber', label: 'User ID' },
            { name: 'gidNumber', label: 'Group ID' },
            { name: 'homeDirectory', label: 'Home folder' },
            { name: 'loginShell', label: 'Shell' },
          ],
        },
        {
          key: 'user/mailAccount',
          label: 'Mail account',
          type: 'user',
          attributes: [{ name: 'mailQuota', label: 'Mailbox quota' }],
        },
      ],
    },
    {
      category: 'group',
      label: 'Groups',
      wildcard: 'group/0',
      objects: [
        {
          key: 'group/group',
          label: 'Group',
          type: 'group',
          attributes: [
            { name: 'cn', label: 'Name' },
            { name: 'description', label: 'Description' },
            { name: 'member', label: 'Members' },
          ],
        },
      ],
    },
    {
      category: 'department',
      label: 'Departments',
      wildcard: 'department/0',
      objects: [
        {
          key: 'department/department',
          label: 'Department',
          type: 'department',
          attributes: [
            { name: 'ou', label: 'Name' },
            { name: 'description', label: 'Description' },
          ],
        },
      ],
    },
    {
      category: 'role',
      label: 'Organizational roles',
      wildcard: 'role/0',
      objects: [
        {
          key: 'role/role',
          label: 'Organizational role',
          type: 'role',
          attributes: [
            { name: 'cn', label: 'Name' },
            { name: 'roleOccupant', label: 'Members' },
          ],
        },
      ],
    },
    {
      category: 'acl',
      label: 'Access control',
      wildcard: 'acl/0',
      objects: [
        {
          key: 'acl/aclRole',
          label: 'Role definition',
          type: 'role',
          attributes: [{ name: 'cn', label: 'Name' }],
        },
        {
          key: 'acl/aclAssignment',
          label: 'Assignment',
          type: 'role',
          attributes: [{ name: 'cn', label: 'Name' }],
        },
      ],
    },
  ],
}

interface FieldSeed {
  key: string
  section: string
  kind: ConfigKind
  honoured?: boolean
  options?: string[]
  secret?: boolean
  value: ConfigValue
  stored?: boolean
}

const FIELD_SEEDS: FieldSeed[] = [
  { key: 'language', section: 'look_and_feel', kind: 'select', options: ['en', 'fr'], value: 'en' },
  { key: 'timezone', section: 'look_and_feel', kind: 'str', value: 'UTC' },
  { key: 'min_id', section: 'core', kind: 'int', honoured: true, value: 0 },
  { key: 'shells', section: 'core', kind: 'list', honoured: true, value: ['/bin/bash', '/bin/sh'] },
  { key: 'strict_naming_rules', section: 'core', kind: 'bool', value: false },
  { key: 'password_min_length', section: 'password', kind: 'int', honoured: true, value: 8 },
  { key: 'password_default_hash', section: 'password', kind: 'str', honoured: true, value: 'ssha' },
  { key: 'login_attribute', section: 'login', kind: 'str', honoured: true, value: 'uid' },
  { key: 'session_lifetime', section: 'login', kind: 'int', honoured: true, value: 1800 },
  {
    key: 'login_method',
    section: 'login',
    kind: 'select',
    options: ['form', 'http_basic', 'http_header', 'cas'],
    value: 'form',
  },
  { key: 'cas_host', section: 'login', kind: 'str', value: '' },
  { key: 'ssl_ca_cert_path', section: 'ssl', kind: 'path', value: '' },
  { key: 'user_rdn', section: 'storage', kind: 'str', honoured: true, value: 'ou=people' },
  { key: 'snapshots_enabled', section: 'snapshots', kind: 'bool', value: true },
  { key: 'recovery_enabled', section: 'recovery', kind: 'bool', value: true },
  { key: 'recovery_salt', section: 'recovery', kind: 'str', secret: true, value: 'pepper' },
  { key: 'tasks_rdn', section: 'tasks', kind: 'str', value: '' },
  { key: 'mail_template_rdn', section: 'mail_templates', kind: 'str', value: '' },
  { key: 'debug_level', section: 'debugging', kind: 'int', value: 0 },
  { key: 'dashboard_prefix', section: 'misc', kind: 'list', value: [] },
]

const SECTIONS = [
  'look_and_feel',
  'core',
  'password',
  'login',
  'ssl',
  'storage',
  'snapshots',
  'triggers',
  'recovery',
  'tasks',
  'mail_templates',
  'debugging',
  'misc',
]

function role(
  cn: string,
  description: string,
  blocks: AclRole['templates'][number]['blocks'],
  raw: string,
): AclRole {
  return {
    dn: `cn=${cn},${ROLES_DN}`,
    cn,
    description,
    templates: [{ index: 0, raw, blocks }],
  }
}

function initialRoles(): AclRole[] {
  return [
    role(
      'manager',
      'Full management of user accounts',
      [
        { object: 'user/user', rights: 'cmdrw', attributes: [] },
        { object: 'user/posixAccount', rights: 'cmdrw', attributes: [] },
      ],
      '0:user/user;cmdrw,user/posixAccount;cmdrw',
    ),
    role(
      'helpdesk',
      'Resets passwords and keeps contact details up to date',
      [
        {
          object: 'user/user',
          rights: 'rw',
          attributes: [
            { name: 'userPassword', rights: 'w' },
            { name: 'telephoneNumber', rights: 'rw' },
          ],
        },
        { object: 'group/group', rights: 'r', attributes: [] },
      ],
      '0:user/user;rw#userPassword;w#telephoneNumber;rw,group/group;r',
    ),
    role(
      'hr',
      'Reads user accounts and edits employee data',
      [
        {
          object: 'user/user',
          rights: 'rw',
          attributes: [{ name: 'employeeType', rights: 'rw' }],
        },
        { object: 'department/department', rights: 'r', attributes: [] },
      ],
      '0:user/user;rw#employeeType;rw,department/department;r',
    ),
    role(
      'auditor',
      'Read-only view of people, groups and departments',
      [
        { object: 'user/user', rights: 'r', attributes: [] },
        { object: 'group/group', rights: 'r', attributes: [] },
        { object: 'department/department', rights: 'r', attributes: [] },
      ],
      '0:user/user;r,group/group;r,department/department;r',
    ),
    role(
      'group-admin',
      'Creates, renames and removes groups',
      [
        { object: 'group/group', rights: 'cmdrw', attributes: [] },
        { object: 'department/department', rights: 'r', attributes: [] },
      ],
      '0:group/group;cmdrw,department/department;r',
    ),
    role(
      'editownpwd',
      'Everyone edits the password of their own account',
      [
        {
          object: 'user/user',
          rights: 's',
          attributes: [{ name: 'userPassword', rights: 'rw' }],
        },
      ],
      '0:user/user;s#userPassword;rw',
    ),
  ]
}

function initialAssignments(): Record<string, Assignment[]> {
  const paris = departments[0]
  const lyon = departments[1]
  const sales = departments[3]
  const users = db.all('user')
  const agent = users[0]?.dn ?? `uid=ada,ou=people,${BASE_DN}`
  const operator = users[1]?.dn ?? `uid=bob,ou=people,${BASE_DN}`
  const groupDn = (name: string) =>
    paris ? `cn=${name},ou=groups,${paris.dn}` : `cn=${name},ou=groups,${BASE_DN}`
  const entry = (roleDn: string, scope: Assignment['scope'], members: Assignment['members'], index: number): Assignment => ({
    raw: `${index}:${scope}:${roleDn}`,
    index,
    scope,
    role: roleDn,
    role_name: roleDn.slice(3, roleDn.indexOf(',')),
    members,
  })
  const everyone = [{ dn: '*', kind: 'everyone' as const }]

  return {
    [BASE_DN]: [
      entry(
        `cn=manager,${ROLES_DN}`,
        'subtree',
        [{ dn: groupDn('admins'), kind: 'group' }],
        0,
      ),
      entry(`cn=editownpwd,${ROLES_DN}`, 'subtree', everyone, 1),
      entry(
        `cn=auditor,${ROLES_DN}`,
        'subtree',
        [{ dn: `cn=auditor,ou=roles,${BASE_DN}`, kind: 'role' }],
        2,
      ),
    ],
    ...(paris
      ? {
          [paris.dn]: [
            entry(
              `cn=helpdesk,${ROLES_DN}`,
              'subtree',
              [{ dn: groupDn('staff'), kind: 'group' }],
              0,
            ),
          ],
        }
      : {}),
    ...(sales
      ? {
          [sales.dn]: [
            entry(
              `cn=hr,${ROLES_DN}`,
              'base',
              [{ dn: groupDn('sales'), kind: 'group' }],
              0,
            ),
          ],
        }
      : {}),
    ...(lyon
      ? {
          [lyon.dn]: [
            entry(
              `cn=group-admin,${ROLES_DN}`,
              'subtree',
              [{ dn: `cn=it-operator,ou=roles,${BASE_DN}`, kind: 'role' }],
              0,
            ),
            entry(`cn=helpdesk,${ROLES_DN}`, 'base', [{ dn: agent, kind: 'user' }], 1),
            entry(`cn=auditor,${ROLES_DN}`, 'base', [{ dn: operator, kind: 'user' }], 2),
          ],
        }
      : {}),
  }
}

function initialChecks(): HealthCheck[] {
  return [
    { id: 'root_object', status: 'ok', message: 'The base entry is correct.', dns: [], fixable: false, options: [] },
    {
      id: 'super_admin',
      status: 'error',
      message: 'No super administrator found.',
      dns: [],
      fixable: true,
      options: ['dn'],
    },
    {
      id: 'default_roles',
      status: 'warning',
      message: 'Missing default roles: editowninfos.',
      dns: [`cn=editowninfos,${ROLES_DN}`],
      fixable: true,
      options: [],
    },
    {
      id: 'users_tree',
      status: 'warning',
      message: '2 users are outside the people tree.',
      dns: [`uid=a,ou=misc,${BASE_DN}`, `uid=b,ou=misc,${BASE_DN}`],
      fixable: true,
      options: [],
    },
    {
      id: 'duplicate_ids',
      status: 'warning',
      message: 'Duplicated identifiers: uidNumber 1001.',
      dns: [`uid=c,ou=people,${BASE_DN}`],
      fixable: false,
      options: [],
    },
  ]
}

function initialPlugins(): PluginInfo[] {
  return [
  {
    name: 'posix',
    version: '0.1.0',
    enabled: true,
    available: true,
    missing_object_classes: [],
    required_object_classes: ['posixAccount'],
    types: [{ name: 'posix_group', label: 'Unix group', category: 'directory' }],
    tabs: [{ type: 'user', name: 'posix', label: 'Unix' }],
  },
  {
    name: 'dns',
    version: '0.3.0',
    enabled: false,
    available: true,
    missing_object_classes: [],
    required_object_classes: ['dNSZone'],
    types: [{ name: 'dns_zone', label: 'DNS zone', category: 'systems' }],
    tabs: [],
  },
  {
    name: 'acl_admin',
    version: '0.1.0',
    enabled: true,
    available: true,
    locked: true,
    missing_object_classes: [],
    required_object_classes: [],
    types: [],
    tabs: [],
  },
  {
    name: 'samba',
    version: '0.2.0',
    enabled: false,
    available: false,
    missing_object_classes: ['sambaSamAccount'],
    required_object_classes: ['sambaSamAccount'],
    types: [],
    tabs: [],
  },
  ]
}

function initialTasks(): TaskRow[] {
  return [
    {
      dn: `cn=purge-audit,ou=tasks,${BASE_DN}`,
      name: 'purge-audit',
      kind: 'audit_task',
      kind_label: 'Audit purge',
      status: 'Activated',
      created: '2026-01-01T10:00:00+00:00',
      last_run: '2026-01-02T10:00:00+00:00',
      next_run: null,
      subtasks: { total: 4, done: 3, failed: 1 },
      failed_subtasks: [`cn=sub1,ou=tasks,${BASE_DN}`],
      can_run: true,
      last_report: {
        time: '2026-01-02T10:00:01+00:00',
        status: 'ok',
        summary: 'events_purged 5',
        errors: [],
      },
    },
    {
      dn: `cn=old-reminder,ou=tasks,${BASE_DN}`,
      name: 'old-reminder',
      kind: 'reminder_task',
      kind_label: 'Reminder',
      status: 'Deactivated',
      created: null,
      last_run: null,
      next_run: null,
      subtasks: { total: 0, done: 0, failed: 0 },
      failed_subtasks: [],
      can_run: false,
    },
  ]
}

/** Mutable state behind the administration endpoints (reset it between tests). */
export const adminMock = {
  roles: initialRoles(),
  assignments: initialAssignments(),
  values: new Map<string, ConfigValue>(),
  hooks: [] as Hook[],
  displayOutput: false,
  checks: initialChecks(),
  tasks: initialTasks(),
  plugins: initialPlugins(),
  /** Makes the next plugin toggle fail (to test the rollback). */
  failPluginToggle: false,
  requests: [] as { method: string; path: string; body: unknown }[],
  reset() {
    this.roles = initialRoles()
    this.assignments = initialAssignments()
    this.values = new Map()
    this.hooks = []
    this.displayOutput = false
    this.checks = initialChecks()
    this.tasks = initialTasks()
    this.plugins = initialPlugins()
    this.failPluginToggle = false
    this.requests = []
  },
}

function capabilities(): Capabilities {
  const user = db.session.user
  if (user === 'employee')
    return {
      is_admin: false,
      console: false,
      acl: false,
      config: false,
      config_write: false,
      hooks: false,
      health: false,
      plugins: false,
      tasks: false,
    }
  if (user === 'viewer')
    return {
      is_admin: false,
      console: true,
      acl: false,
      config: true,
      config_write: false,
      hooks: true,
      health: true,
      plugins: true,
      tasks: false,
    }
  return {
    is_admin: true,
    console: true,
    acl: true,
    config: true,
    config_write: true,
    hooks: true,
    health: true,
    plugins: true,
    tasks: true,
  }
}

function configView() {
  const writable = capabilities().config_write
  const fields: ConfigField[] = FIELD_SEEDS.map((s) => {
    const value = adminMock.values.has(s.key) ? (adminMock.values.get(s.key) ?? null) : s.value
    const hidden = !!s.secret && !writable
    return {
      key: s.key,
      section: s.section,
      kind: s.kind,
      honoured: !!s.honoured,
      options: s.options ?? [],
      secret: !!s.secret,
      default: s.value,
      value: hidden ? null : value,
      source: adminMock.values.has(s.key) ? 'directory' : 'default',
      hidden,
    }
  })
  return { exists: adminMock.values.size > 0, can_write: writable, sections: SECTIONS, fields }
}

function hooksView() {
  return {
    hooks: adminMock.hooks,
    invalid: [] as string[],
    display_output: adminMock.displayOutput,
    modes: ['postcreate', 'postmodify', 'postremove', 'precreate', 'premodify', 'preremove', 'check'],
    tabs: ['user', 'posixAccount', 'group'],
    can_write: capabilities().config_write,
  }
}

function record(method: string, path: string, body: unknown): void {
  adminMock.requests.push({ method, path, body })
}

function guarded<
  T extends {
    request: Request
    params: Record<string, string | readonly string[] | undefined>
  },
>(fn: (info: T) => Response | Promise<Response>) {
  return async (info: T): Promise<Response> => {
    if (!db.me()) return err(401, 'unauthenticated', 'Authentication required')
    if (info.request.method !== 'GET' && info.request.headers.get('X-CSRF-Token') !== db.csrf)
      return err(403, 'forbidden', 'Invalid CSRF token')
    return fn(info)
  }
}

// ── a minimal but faithful rights evaluation for the mock ──────────────────

const RIGHT_ORDER = ['s', 'r', 'w', 'c', 'd', 'm', 't']

function unionRights(...values: string[]): string {
  const set = new Set(values.join('').split(''))
  return RIGHT_ORDER.filter((letter) => set.has(letter)).join('')
}

function withoutSelf(rights: string): string {
  return rights.replace(/s/g, '')
}

function objectApplies(blockKey: string, objectKey: string): boolean {
  if (blockKey === objectKey || blockKey === 'all') return true
  return blockKey.endsWith('/0') && objectKey.startsWith(blockKey.slice(0, -1))
}

function isUnder(targetDn: string, entryDn: string): boolean {
  const target = targetDn.trim().toLowerCase()
  const entry = entryDn.trim().toLowerCase()
  return target === entry || target.endsWith(`,${entry}`)
}

function memberMatches(member: { dn: string; kind: string }, userDn: string): boolean {
  if (member.kind === 'everyone' || member.dn === '*') return true
  if (member.dn.toLowerCase() === userDn.trim().toLowerCase()) return true
  if (member.kind === 'group') {
    const group = db.get(member.dn)
    const members = group?.tabs.main?.values.member
    return (
      Array.isArray(members) &&
      members.some((dn) => String(dn).toLowerCase() === userDn.trim().toLowerCase())
    )
  }
  return false
}

function membersOf(assignment: Assignment): { dn: string; kind: string }[] {
  return (assignment.members ?? []).map((m) =>
    typeof m === 'string'
      ? { dn: m, kind: m === '*' ? 'everyone' : 'user' }
      : { dn: m.dn, kind: m.kind },
  )
}

function evaluateRights(
  userDn: string,
  targetDn: string,
  objectKey: string,
  attributes: string[],
): RightsReport {
  const own = targetDn.trim().toLowerCase() === userDn.trim().toLowerCase()
  const bootstrap = userDn.trim().toLowerCase().includes('uid=admin,')
  const rights: string[] = []
  const attributeRights = new Map<string, string>()
  const rules: RightsReport['rules'] = []

  for (const [entryDn, assignments] of Object.entries(adminMock.assignments)) {
    for (const assignment of assignments) {
      if (assignment.ignored || !assignment.role) continue
      if (!membersOf(assignment).some((member) => memberMatches(member, userDn))) continue
      const applies =
        assignment.scope === 'base'
          ? entryDn.toLowerCase() === targetDn.toLowerCase()
          : isUnder(targetDn, entryDn)
      if (!applies) continue
      const roleDefinition = adminMock.roles.find((role) => role.dn === assignment.role)
      if (!roleDefinition) continue
      for (const template of roleDefinition.templates) {
        if (template.ignored) continue
        rules.push({
          origin: entryDn,
          scope: assignment.scope ?? 'subtree',
          blocks: template.blocks.map((b) => b.object).sort(),
        })
        for (const block of template.blocks) {
          if (!objectApplies(block.object, objectKey)) continue
          if (own || !block.rights.includes('s')) rights.push(withoutSelf(block.rights))
          for (const attribute of block.attributes) {
            if (!own && attribute.rights.includes('s')) continue
            const name = attribute.name.toLowerCase()
            attributeRights.set(
              name,
              unionRights(attributeRights.get(name) ?? '', withoutSelf(attribute.rights)),
            )
          }
        }
      }
    }
  }

  const objectRights = bootstrap ? 'rwcdm' : withoutSelf(unionRights(...rights))
  return {
    dn: targetDn,
    object: objectKey,
    rights: objectRights,
    attributes: Object.fromEntries(
      attributes.map((attribute) => [
        attribute,
        bootstrap
          ? 'rw'
          : unionRights(objectRights, attributeRights.get(attribute.toLowerCase()) ?? ''),
      ]),
    ),
    warnings: [],
    rules,
    bootstrap_admin: bootstrap,
  }
}

export const adminHandlers: HttpHandler[] = [
  http.get(`${A}/capabilities`, guarded(() => HttpResponse.json(capabilities()))),

  // ── ACL ──────────────────────────────────────────────────────────────────
  http.get(`${A}/acl/catalog`, guarded(() => HttpResponse.json(catalog))),
  http.get(
    `${A}/acl/roles`,
    guarded(() => {
      const uses = Object.values(adminMock.assignments).flat()
      return HttpResponse.json(
        adminMock.roles.map((role) => ({
          ...role,
          used_by: uses.filter((a) => !a.ignored && a.role === role.dn).length,
        })),
      )
    }),
  ),
  http.post(
    `${A}/acl/roles`,
    guarded(async ({ request }) => {
      const body = (await request.json()) as {
        cn: string
        description: string
        templates: AclRole['templates']
      }
      record('POST', '/acl/roles', body)
      if (!body.cn) return err(422, 'validation', 'Invalid role', { cn: 'A name is required.' })
      const role: AclRole = {
        dn: `cn=${body.cn},${ROLES_DN}`,
        cn: body.cn,
        description: body.description,
        templates: body.templates.map((t, i) => ({ ...t, index: i })),
        used_by: 0,
      }
      adminMock.roles.push(role)
      return HttpResponse.json(role, { status: 201 })
    }),
  ),
  http.put(
    `${A}/acl/roles/:dn`,
    guarded(async ({ request, params }) => {
      const body = (await request.json()) as Partial<AclRole>
      record('PUT', '/acl/roles', body)
      const role = adminMock.roles.find((r) => r.dn === dn(params.dn))
      if (!role) return err(404, 'not_found', 'Role not found')
      if (body.description !== undefined) role.description = body.description
      if (body.templates) role.templates = body.templates
      return HttpResponse.json(role)
    }),
  ),
  http.delete(
    `${A}/acl/roles/:dn`,
    guarded(({ params }) => {
      record('DELETE', '/acl/roles', dn(params.dn))
      adminMock.roles = adminMock.roles.filter((r) => r.dn !== dn(params.dn))
      return new HttpResponse(null, { status: 204 })
    }),
  ),
  http.get(
    `${A}/acl/assignments`,
    guarded(() =>
      HttpResponse.json(
        Object.entries(adminMock.assignments).map(([entry, assignments]) => ({ dn: entry, assignments })),
      ),
    ),
  ),
  http.get(
    `${A}/acl/assignments/:dn`,
    guarded(({ params }) =>
      HttpResponse.json({ dn: dn(params.dn), assignments: adminMock.assignments[dn(params.dn)] ?? [] }),
    ),
  ),
  http.put(
    `${A}/acl/assignments/:dn`,
    guarded(async ({ request, params }) => {
      const body = (await request.json()) as { assignments: Assignment[] }
      record('PUT', '/acl/assignments', body)
      const entry = dn(params.dn)
      adminMock.assignments[entry] = body.assignments.map((a) => ({
        ...a,
        role_name: a.role ? (adminMock.roles.find((r) => r.dn === a.role)?.cn ?? null) : null,
        members: (a.members ?? []).map((m) =>
          typeof m === 'string' ? { dn: m, kind: m === '*' ? ('everyone' as const) : ('user' as const) } : m,
        ),
      }))
      return HttpResponse.json({ dn: entry, assignments: adminMock.assignments[entry] })
    }),
  ),
  http.post(
    `${A}/acl/check`,
    guarded(async ({ request }) => {
      const body = (await request.json()) as {
        user: string
        dn: string
        object: string
        attributes: string[]
      }
      record('POST', '/acl/check', body)
      return HttpResponse.json(evaluateRights(body.user, body.dn, body.object, body.attributes))
    }),
  ),

  // ── configuration ────────────────────────────────────────────────────────
  http.get(`${A}/config`, guarded(() => HttpResponse.json(configView()))),
  http.put(
    `${A}/config`,
    guarded(async ({ request }) => {
      const body = (await request.json()) as { changes: Record<string, ConfigValue> }
      record('PUT', '/config', body)
      if (!capabilities().config_write) return err(403, 'forbidden', 'Not allowed')
      const unknown: Record<string, string> = {}
      for (const [k, v] of Object.entries(body.changes)) {
        const seed = FIELD_SEEDS.find((s) => s.key === k)
        if (!seed) unknown[k] = 'Unknown setting.'
        else if (seed.kind === 'int' && v !== null && typeof v !== 'number')
          unknown[k] = 'Expected a whole number.'
      }
      if (Object.keys(unknown).length > 0) return err(422, 'validation', 'Invalid configuration', unknown)
      for (const [k, v] of Object.entries(body.changes)) adminMock.values.set(k, v)
      return HttpResponse.json(configView())
    }),
  ),

  // ── triggers ─────────────────────────────────────────────────────────────
  http.get(`${A}/hooks`, guarded(() => HttpResponse.json(hooksView()))),
  http.put(
    `${A}/hooks`,
    guarded(async ({ request }) => {
      const body = (await request.json()) as { hooks: Hook[]; display_output?: boolean }
      record('PUT', '/hooks', body)
      const errors: Record<string, string> = {}
      body.hooks.forEach((h, i) => {
        if (!h.command.trim()) errors[`hooks.${i}.command`] = 'A single-line command is required.'
      })
      if (Object.keys(errors).length > 0) return err(422, 'validation', 'Invalid triggers', errors)
      adminMock.hooks = body.hooks
      if (body.display_output !== undefined) adminMock.displayOutput = body.display_output
      return HttpResponse.json(hooksView())
    }),
  ),

  // ── health ───────────────────────────────────────────────────────────────
  http.get(`${A}/checks`, guarded(() => HttpResponse.json(adminMock.checks))),
  http.post(
    `${A}/checks/:id/fix`,
    guarded(async ({ request, params }) => {
      const body = (await request.json()) as { dns: string[]; options: Record<string, string> }
      record('POST', `/checks/${String(params.id)}/fix`, body)
      const check = adminMock.checks.find((c) => c.id === params.id)
      if (!check?.fixable) return err(404, 'not_found', 'This check has no fix')
      const fixed = check.options.includes('dn') ? (body.options.dn ? [body.options.dn] : []) : body.dns
      const remaining = check.dns.filter((d) => !fixed.includes(d))
      const next: HealthCheck = remaining.length === 0 || check.options.includes('dn')
        ? { ...check, status: 'ok', message: 'Fixed.', dns: [], fixable: false, options: [] }
        : { ...check, dns: remaining }
      adminMock.checks = adminMock.checks.map((c) => (c.id === check.id ? next : c))
      return HttpResponse.json({
        result: { id: check.id, fixed, failed: {}, message: '' },
        check: next,
      })
    }),
  ),

  // ── plugins and tasks ────────────────────────────────────────────────────
  http.get(`${A}/plugins`, guarded(() => HttpResponse.json(adminMock.plugins))),
  http.patch(
    `${A}/plugins/:name`,
    guarded(async ({ request, params }) => {
      const body = (await request.json()) as { enabled: boolean }
      record('PATCH', `/plugins/${String(params.name)}`, body)
      if (adminMock.failPluginToggle) return err(409, 'plugin_unavailable', 'Unavailable')
      const plugin = adminMock.plugins.find((p) => p.name === params.name)
      if (!plugin) return err(404, 'not_found', 'Unknown plugin')
      plugin.enabled = body.enabled
      return HttpResponse.json({ restart_required: false, plugin })
    }),
  ),
  http.get(
    `${A}/tasks`,
    guarded(({ request }) => {
      const u = new URL(request.url)
      const kind = u.searchParams.get('kind')
      const status = u.searchParams.get('status')
      const rows = adminMock.tasks.filter(
        (r) => (!kind || r.kind === kind) && (!status || r.status.toLowerCase() === status.toLowerCase()),
      )
      return HttpResponse.json({
        tasks: rows,
        kinds: [
          { name: 'audit_task', label: 'Audit purge' },
          { name: 'reminder_task', label: 'Reminder' },
        ],
        summary: {
          total: rows.length,
          active: rows.filter((r) => r.status === 'Activated').length,
          failed_subtasks: rows.reduce((n, r) => n + r.subtasks.failed, 0),
        },
        capabilities: { syslog_configured: false, scheduler_in_process: true, run_history: true },
      })
    }),
  ),
  http.get(
    `${A}/tasks/runs`,
    guarded(() =>
      HttpResponse.json({
        runs: [
          {
            id: 2,
            directory: 'main',
            runner: 'audit',
            kind: 'audit_task',
            started: '2030-01-02T03:04:00+00:00',
            finished: '2030-01-02T03:04:01+00:00',
            status: 'ok',
            counts: { events_purged: 5 },
            errors: [],
            summary: 'events_purged 5',
          },
          {
            id: 1,
            directory: 'main',
            runner: 'user_reminder',
            kind: 'reminder_task',
            started: '2030-01-02T03:04:00+00:00',
            finished: '2030-01-02T03:04:00+00:00',
            status: 'skipped',
            counts: {},
            errors: ['no mail server is configured: the runner was skipped'],
            summary: '1 error(s)',
          },
        ],
      }),
    ),
  ),
  http.post(
    `${A}/tasks/:dn/run`,
    guarded(({ params }) => {
      record('POST', '/tasks/run', dn(params.dn))
      return HttpResponse.json({ dn: dn(params.dn), queued: false, runs: [] })
    }),
  ),
  http.post(
    `${A}/tasks/:dn/retry`,
    guarded(({ params }) => {
      record('POST', '/tasks/retry', dn(params.dn))
      const row = adminMock.tasks.find((r) => r.dn === dn(params.dn))
      const retried = row?.failed_subtasks ?? []
      if (row) {
        row.subtasks = { ...row.subtasks, failed: 0 }
        row.failed_subtasks = []
      }
      return HttpResponse.json({ dn: dn(params.dn), retried })
    }),
  ),
]

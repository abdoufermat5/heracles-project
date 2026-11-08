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
import { BASE_DN, db } from './db'

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
          label: 'User',
          type: 'user',
          attributes: [
            { name: 'sn', label: 'Surname' },
            { name: 'userPassword', label: 'Password' },
          ],
        },
        {
          key: 'user/posixAccount',
          label: 'Unix',
          type: 'user',
          attributes: [{ name: 'loginShell', label: 'Shell' }],
        },
      ],
    },
    {
      category: 'group',
      label: 'Groups',
      wildcard: 'group/0',
      objects: [
        { key: 'group/group', label: 'Group', type: 'group', attributes: [{ name: 'cn', label: 'Name' }] },
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

function initialRoles(): AclRole[] {
  return [
    {
      dn: `cn=manager,${ROLES_DN}`,
      cn: 'manager',
      description: 'All rights on users',
      used_by: 1,
      templates: [
        {
          raw: '0:user/user;cmdrw,user/posixAccount;cmdrw',
          index: 0,
          blocks: [
            { object: 'user/user', rights: 'cmdrw', attributes: [] },
            { object: 'user/posixAccount', rights: 'cmdrw', attributes: [] },
          ],
        },
      ],
    },
    {
      dn: `cn=editownpwd,${ROLES_DN}`,
      cn: 'editownpwd',
      description: 'Users edit their own password',
      used_by: 0,
      templates: [
        {
          raw: '0:user/user;s#userPassword;rw',
          index: 0,
          blocks: [
            {
              object: 'user/user',
              rights: 's',
              attributes: [{ name: 'userPassword', rights: 'rw' }],
            },
          ],
        },
      ],
    },
  ]
}

function initialAssignments(): Record<string, Assignment[]> {
  return {
    [BASE_DN]: [
      {
        raw: `0:subtree:cn=manager,${ROLES_DN}:uid=ada,ou=people,${BASE_DN}`,
        index: 0,
        scope: 'subtree',
        role: `cn=manager,${ROLES_DN}`,
        role_name: 'manager',
        members: [{ dn: `uid=ada,ou=people,${BASE_DN}`, kind: 'user' }],
      },
    ],
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

const PLUGINS: PluginInfo[] = [
  {
    name: 'posix',
    version: '0.1.0',
    enabled: true,
    missing_object_classes: [],
    required_object_classes: ['posixAccount'],
    types: [{ name: 'posix_group', label: 'Unix group', category: 'directory' }],
    tabs: [{ type: 'user', name: 'posix', label: 'Unix' }],
  },
  {
    name: 'samba',
    version: '0.2.0',
    enabled: false,
    missing_object_classes: ['sambaSamAccount'],
    required_object_classes: ['sambaSamAccount'],
    types: [],
    tabs: [],
  },
]

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
  requests: [] as { method: string; path: string; body: unknown }[],
  reset() {
    this.roles = initialRoles()
    this.assignments = initialAssignments()
    this.values = new Map()
    this.hooks = []
    this.displayOutput = false
    this.checks = initialChecks()
    this.tasks = initialTasks()
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

export const adminHandlers: HttpHandler[] = [
  http.get(`${A}/capabilities`, guarded(() => HttpResponse.json(capabilities()))),

  // ── ACL ──────────────────────────────────────────────────────────────────
  http.get(`${A}/acl/catalog`, guarded(() => HttpResponse.json(catalog))),
  http.get(`${A}/acl/roles`, guarded(() => HttpResponse.json(adminMock.roles))),
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
      const body = (await request.json()) as { user: string; dn: string; object: string; attributes: string[] }
      record('POST', '/acl/check', body)
      const report: RightsReport = {
        dn: body.dn,
        object: body.object,
        rights: 'rw',
        attributes: Object.fromEntries(body.attributes.map((a) => [a, 'r'])),
        warnings: [],
        rules: [{ origin: BASE_DN, scope: 'subtree', blocks: [`${body.object};rw`] }],
        bootstrap_admin: false,
      }
      return HttpResponse.json(report)
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
  http.get(`${A}/plugins`, guarded(() => HttpResponse.json(PLUGINS))),
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
      })
    }),
  ),
  http.post(
    `${A}/tasks/:dn/run`,
    guarded(({ params }) => {
      record('POST', '/tasks/run', dn(params.dn))
      return HttpResponse.json({ dn: dn(params.dn), queued: true })
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

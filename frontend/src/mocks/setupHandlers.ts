import { http, HttpResponse, type HttpHandler } from 'msw'
import { matchesFormat } from '@/lib/formats'

const B = '/api/v2/setup'

/** Knobs for tests and the dev mock: flip `required` to simulate a server in setup mode. */
export const setupMock = {
  required: false,
  token: 'setup-token-123',
  /** classes reported missing until `schemaInstalled` becomes true */
  schemaInstalled: true,
  applied: null as unknown,
}

export function resetSetupMock(): void {
  setupMock.required = false
  setupMock.schemaInstalled = true
  setupMock.applied = null
}

const MISSING = ['hrcPerson', 'hrcGroup']

function bad(code: string, message: string, status = 401) {
  return HttpResponse.json({ error: { code, message } }, { status })
}

const tokenOk = (r: Request) => r.headers.get('X-Setup-Token') === setupMock.token

interface TestBody {
  uri: string
  bind_dn: string
  bind_password: string
  base_dn: string
  ca_file?: string | null
  starttls?: boolean
}

interface ApplyDirectory extends TestBody {
  id?: string
  label?: string
}

/** `ldap://host[:port]`, `ldaps://host[:port]` or `ldapi://<socket path>`. */
const URI_RE = /^(?:ldaps?:\/\/(\[[0-9A-Fa-f:.]+\]|[^/:\s]+)(?::(\d+))?|ldapi:\/\/\S+)$/
const LOGIN_RE = /^[A-Za-z0-9._-]{1,64}$/
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

/**
 * Field problems of a directory section, mirroring `heracles.setup.service.validate_directory`:
 * keys relative to the body (`directory.` added by the apply step, as the server does).
 */
function directoryFields(body: ApplyDirectory, baseRequired: boolean): Record<string, string> {
  const fields: Record<string, string> = {}
  const put = (key: string, problem: string | null) => {
    if (problem !== null) fields[key] = problem
  }
  const uris = body.uri.trim().split(/\s+/).filter(Boolean)
  if (uris.length === 0) put('uri', 'The server address is required.')
  else {
    for (const uri of uris) {
      const found = URI_RE.exec(uri)
      const host = found?.[1]
      const port = found?.[2]
      if (!found) {
        put('uri', 'Use an address such as ldap://host:389 or ldaps://host:636.')
        break
      }
      if (host && !host.startsWith('[') && !matchesFormat('hostname', host)) {
        put('uri', 'The server address has no valid host name.')
        break
      }
      if (port && !matchesFormat('port', port)) {
        put('uri', 'The port must be between 1 and 65535.')
        break
      }
    }
  }
  const base = body.base_dn.trim()
  if (base === '') {
    if (baseRequired) put('base_dn', 'The base DN is required.')
  } else if (!matchesFormat('dn', base)) {
    put('base_dn', 'Enter a distinguished name such as cn=admin,dc=example,dc=org.')
  }
  const bind = body.bind_dn.trim()
  if (bind !== '' && !matchesFormat('dn', bind)) {
    put('bind_dn', 'Enter a distinguished name such as cn=admin,dc=example,dc=org.')
  } else if (bind !== '' && body.bind_password === '') {
    put('bind_password', 'The password of the service account is required.')
  }
  const ca = (body.ca_file ?? '').trim()
  if (ca !== '' && !matchesFormat('abs_path', ca)) {
    put('ca_file', 'Enter an absolute path such as /etc/ssl/certs/ca.pem.')
  }
  if (body.starttls && /^ldaps:\/\//i.test(body.uri.trim())) {
    put('starttls', 'Use either an ldaps:// address or StartTLS, not both.')
  }
  return fields
}

/** Administrator and review fields of the apply step (`heracles.setup.service._validate`). */
function applyFields(body: {
  directory: ApplyDirectory
  admin: { uid: string; given_name: string; surname: string; mail: string; password: string }
  plugins: string[]
  public_url: string | null
}): Record<string, string> {
  const fields: Record<string, string> = {}
  for (const [key, problem] of Object.entries(directoryFields(body.directory, true))) {
    fields[`directory.${key}`] = problem
  }
  const dir = body.directory
  if (dir.id !== undefined && !/^[A-Za-z0-9._-]+$/.test(dir.id)) {
    fields['directory.id'] = 'Use letters, digits, dots, dashes and underscores.'
  }
  if ((dir.label ?? '').length > 80) fields['directory.label'] = 'Use at most 80 characters.'
  const admin = body.admin
  if (!admin.uid.trim()) fields['admin.uid'] = 'The login is required.'
  else if (!LOGIN_RE.test(admin.uid)) {
    fields['admin.uid'] = 'Use up to 64 letters, digits, dots, dashes and underscores.'
  }
  for (const [key, value, label] of [
    ['given_name', admin.given_name, 'first name'],
    ['surname', admin.surname, 'last name'],
  ] as const) {
    const text = value.trim()
    if (!text) fields[`admin.${key}`] = `The ${label} is required.`
    else if (text.length > 128 || [...text].some((ch) => ch.charCodeAt(0) < 32)) {
      fields[`admin.${key}`] = 'Use at most 128 characters, no control characters.'
    }
  }
  if (admin.mail && !EMAIL_RE.test(admin.mail)) fields['admin.mail'] = 'This is not a valid address.'
  if (admin.password.length < 8) fields['admin.password'] = 'Password must be at least 8 characters long'
  const url = (body.public_url ?? '').trim()
  if (url !== '') {
    try {
      const parsed = new URL(url)
      if (
        (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') ||
        parsed.hostname === ''
      )
        fields.public_url = 'Use a full address such as https://heracles.example.org.'
    } catch {
      fields.public_url = 'Use a full address such as https://heracles.example.org.'
    }
  }
  if (body.plugins.length === 0) fields.plugins = 'Choose at least one plugin.'
  return fields
}

function refuse(fields: Record<string, string>) {
  return HttpResponse.json(
    { error: { code: 'validation', message: 'Some fields are not valid', fields } },
    { status: 422 },
  )
}

export const setupHandlers: HttpHandler[] = [
  http.get(`${B}/status`, () =>
    HttpResponse.json({
      setup_required: setupMock.required,
      version: '0.1.0',
      config_path: '/var/lib/heracles/config.yaml',
    }),
  ),
  http.post(`${B}/token/verify`, ({ request }) =>
    tokenOk(request)
      ? new HttpResponse(null, { status: 204 })
      : bad('setup_token_invalid', 'The setup token is not valid.'),
  ),
  http.post(`${B}/directory/test`, async ({ request }) => {
    if (!tokenOk(request)) return bad('setup_token_invalid', 'The setup token is not valid.')
    const body = (await request.json()) as TestBody
    // the server validates the whole section (base DN optional) before connecting, with
    // the fields relative to this flat body
    const refused = directoryFields(body, false)
    if (Object.keys(refused).length) return refuse(refused)
    if (body.bind_password !== 'secret') {
      return HttpResponse.json({
        ok: false,
        error: { code: 'bind_failed', message: 'Invalid credentials for the bind DN.' },
        naming_contexts: [],
        base_dn_exists: false,
        can_write: false,
        schema: { installed: false, missing_classes: [] },
      })
    }
    return HttpResponse.json({
      ok: true,
      error: null,
      naming_contexts: ['dc=example,dc=org'],
      base_dn_exists: body.base_dn === 'dc=example,dc=org',
      can_write: true,
      schema: {
        installed: setupMock.schemaInstalled,
        missing_classes: setupMock.schemaInstalled ? [] : MISSING,
      },
    })
  }),
  http.get(`${B}/schema`, ({ request }) => {
    if (!tokenOk(request)) return bad('setup_token_invalid', 'The setup token is not valid.')
    const format = new URL(request.url).searchParams.get('format') ?? 'ldif'
    return new HttpResponse(`# heracles ${format} schema\n`, {
      headers: { 'Content-Type': 'text/plain' },
    })
  }),
  http.get(`${B}/plugins`, ({ request }) => {
    if (!tokenOk(request)) return bad('setup_token_invalid', 'The setup token is not valid.')
    return HttpResponse.json({
      profiles: [
        { id: 'core', plugins: ['posix', 'audit'] },
        { id: 'all', plugins: ['posix', 'audit', 'mail', 'dns'] },
      ],
      plugins: [
        { name: 'posix', label: 'Linux and Unix accounts', description: 'Shell, home directory and UID numbers.', default: true },
        { name: 'audit', label: 'Audit log', description: 'Records who changed what.', default: true },
        { name: 'mail', label: 'Mail accounts', description: 'Mailboxes and aliases.', default: false },
        { name: 'dns', label: 'DNS zones', description: 'Zones and records.', default: false },
      ],
    })
  }),
  http.post(`${B}/apply`, async ({ request }) => {
    if (!tokenOk(request)) return bad('setup_token_invalid', 'The setup token is not valid.')
    const body = (await request.json()) as {
      directory: ApplyDirectory
      admin: { uid: string; given_name: string; surname: string; mail: string; password: string }
      plugins: string[]
      public_url: string | null
    }
    // the server validates the directory, the administrator, the plugins and the address
    // before writing anything (keys prefixed as the apply step reports them)
    const refused = applyFields(body)
    if (Object.keys(refused).length) return refuse(refused)
    setupMock.applied = body
    setupMock.required = false
    return HttpResponse.json({ ok: true, config_path: '/var/lib/heracles/config.yaml', login_url: '/login' })
  }),
]

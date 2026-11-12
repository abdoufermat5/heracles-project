import { http, HttpResponse, type HttpHandler } from 'msw'

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
    const body = (await request.json()) as { admin: { password: string } }
    if (body.admin.password.length < 8) {
      return HttpResponse.json(
        {
          error: {
            code: 'validation',
            message: 'Some values are not valid.',
            fields: { 'admin.password': 'Use at least 8 characters.' },
          },
        },
        { status: 422 },
      )
    }
    setupMock.applied = body
    setupMock.required = false
    return HttpResponse.json({ ok: true, config_path: '/var/lib/heracles/config.yaml', login_url: '/login' })
  }),
]

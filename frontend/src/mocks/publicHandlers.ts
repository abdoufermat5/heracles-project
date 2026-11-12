import { http, HttpResponse } from 'msw'
import { leadingZeroBits, sha256Short } from '@/features/auth/pow'
import type { PublicForm } from '@/features/public/api'

/** Mock of `/api/v2/public/forms/*`: same shapes and status codes as the backend plugin. */
const B = '/api/v2/public/forms'

/** Low on purpose (the server default is 20 bits) so tests and the dev server answer instantly. */
export const MOCK_DIFFICULTY = 4
/** One second here (3 on the server) to keep the dev server and the tests quick. */
export const MOCK_MIN_FILL = 1
export const VALID_INVITATION = 'valid-invitation-token'

const field = (attr: string, label: string, kind: string, required = true) => ({
  key: `main.${attr}`,
  tab: 'main',
  name: attr,
  label,
  description: '',
  kind,
  required,
  multivalued: false,
  readonly: false,
  default: null,
  constraints: {},
  value: null,
})

function forms(): Record<string, PublicForm> {
  const base = {
    text: 'Fill in the form to create your account.',
    final_text: 'Your account has been created. You can now sign in.',
    captcha: true,
    tos_url: '',
    invitee_email: null,
    invitation_required: false,
  }
  const fields = [
    field('givenName', 'First name', 'string'),
    field('sn', 'Last name', 'string'),
    field('mail', 'Email address', 'email'),
  ] as unknown as PublicForm['fields']
  return {
    register: { ...base, name: 'register', title: 'Create your account', private: false, fields },
    join: { ...base, name: 'join', title: 'Join the team', private: true, fields },
  }
}

const used = new Set<string>()

function error(status: number, code: string, message: string, fields?: Record<string, string>, headers?: HeadersInit) {
  return HttpResponse.json({ error: { code, message, ...(fields ? { fields } : {}) } }, { status, headers })
}

function challenge() {
  const now = Date.now() / 1000
  const nonce = Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
  const payload = JSON.stringify({ n: nonce, d: MOCK_DIFFICULTY, i: now, e: now + 600 })
  return {
    token: `${btoa(payload).replace(/\+/g, '-').replace(/\//g, '_')}.mock-signature`,
    nonce,
    difficulty: MOCK_DIFFICULTY,
    algorithm: 'sha256' as const,
    min_fill_seconds: MOCK_MIN_FILL,
  }
}

function verify(token: unknown, answer: unknown): boolean {
  if (typeof token !== 'string' || typeof answer !== 'string' || !/^\d{1,15}$/.test(answer)) return false
  try {
    const data = JSON.parse(atob((token.split('.')[0] ?? '').replace(/-/g, '+').replace(/_/g, '/'))) as {
      n: string
      d: number
      i: number
    }
    if (used.has(data.n) || Date.now() / 1000 - data.i < MOCK_MIN_FILL) return false
    const ok = leadingZeroBits(sha256Short(new TextEncoder().encode(`${data.n}:${answer}`))) >= data.d
    if (ok) used.add(data.n)
    return ok
  } catch {
    return false
  }
}

export const publicHandlers = [
  http.get(`${B}/:name`, ({ params, request }) => {
    const form = forms()[String(params.name)]
    if (!form) return error(404, 'not_found', 'Form not found')
    const token = new URL(request.url).searchParams.get('token')
    if (token && token !== VALID_INVITATION && form.private) return error(404, 'not_found', 'Form not found')
    return HttpResponse.json({ ...form, invitation_required: form.private && token !== VALID_INVITATION })
  }),
  http.get(`${B}/:name/captcha`, ({ params }) =>
    forms()[String(params.name)] ? HttpResponse.json(challenge()) : error(404, 'not_found', 'Form not found'),
  ),
  http.post(`${B}/:name`, async ({ params, request }) => {
    const form = forms()[String(params.name)]
    if (!form) return error(404, 'not_found', 'Form not found')
    const body = (await request.json()) as {
      values: Record<string, string>
      token?: string
      captcha_token?: string
      captcha_answer?: string
      website?: string
    }
    // A filled honeypot is answered like a success and creates nothing.
    if (body.website) return HttpResponse.json({ status: 'ok', message: '' }, { status: 201 })
    if (form.private && body.token !== VALID_INVITATION) return error(404, 'not_found', 'Form not found')
    if (form.captcha && !verify(body.captcha_token, body.captcha_answer)) {
      return error(422, 'validation', 'The check failed', { captcha_answer: 'The check failed, try again.' })
    }
    const missing = Object.fromEntries(
      form.fields.filter((f) => f.required && !body.values[f.key]).map((f) => [f.key, 'This field is required.']),
    )
    if (Object.keys(missing).length) return error(422, 'validation', 'Some fields are invalid', missing)
    return HttpResponse.json({ status: 'ok', message: form.final_text }, { status: 201 })
  }),
]

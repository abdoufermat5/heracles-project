import type { AttributeDescriptor } from '@/api/types'
import type { PowChallenge } from '@/features/auth/pow'

/** One field of a public form, as `GET /public/forms/{name}` describes it. */
export interface PublicField extends AttributeDescriptor {
  key: string
  tab: string
  readonly: boolean
  value: unknown
}

export interface PublicForm {
  name: string
  title: string
  text: string
  final_text: string
  private: boolean
  captcha: boolean
  tos_url: string
  invitee_email: string | null
  invitation_required: boolean
  fields: PublicField[]
}

export interface SubmitPayload {
  values: Record<string, unknown>
  token?: string
  captcha_token?: string
  captcha_answer?: string
  website: string
  accept_terms: boolean
}

export class PublicApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly fields: Record<string, string>,
    /** Seconds to wait before trying again (429 `Retry-After`). */
    readonly retryAfter: number | null,
  ) {
    super(message)
    this.name = 'PublicApiError'
  }
}

const BASE = '/api/v2/public/forms'

/** Plain fetch: these endpoints are anonymous (no session, no CSRF, no sign-in redirect). */
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}) },
    })
  } catch {
    throw new PublicApiError(0, 'network', 'Network error', {}, null)
  }
  if (res.ok) return (await res.json()) as T
  let body: { error?: { code?: string; message?: string; fields?: Record<string, string> } } = {}
  try {
    body = (await res.json()) as typeof body
  } catch {
    /* no JSON body */
  }
  const wait = Number.parseInt(res.headers.get('Retry-After') ?? '', 10)
  throw new PublicApiError(
    res.status,
    body.error?.code ?? 'internal',
    body.error?.message ?? res.statusText,
    body.error?.fields ?? {},
    Number.isFinite(wait) ? wait : null,
  )
}

export const publicApi = {
  form: (name: string, token?: string): Promise<PublicForm> =>
    call(`/${encodeURIComponent(name)}${token ? `?token=${encodeURIComponent(token)}` : ''}`),
  captcha: (name: string): Promise<PowChallenge> => call(`/${encodeURIComponent(name)}/captcha`),
  submit: (name: string, body: SubmitPayload): Promise<{ status: 'ok'; message: string }> =>
    call(`/${encodeURIComponent(name)}`, { method: 'POST', body: JSON.stringify(body) }),
}

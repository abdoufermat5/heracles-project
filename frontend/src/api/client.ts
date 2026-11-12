import type { ApiErrorBody, CsrfResponse, ErrorCode, LockInfo } from './types'

export const API_BASE = '/api/v2'

export class ApiError extends Error {
  readonly status: number
  readonly code: ErrorCode | (string & {})
  readonly fields: Record<string, string>
  readonly lock: LockInfo | undefined
  /** `X-Request-ID` of the failed response: quote it to find the server log line. */
  readonly requestId: string | undefined

  constructor(status: number, body: ApiErrorBody['error'], requestId?: string) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.fields = body.fields ?? {}
    this.lock = body.lock
    this.requestId = requestId
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError
}

let csrfToken: string | null = null
let csrfPromise: Promise<string> | null = null
let onUnauthenticated: (() => void) | null = null

/** Registered by the router so a 401 anywhere sends the user to login. */
export function setUnauthenticatedHandler(fn: (() => void) | null): void {
  onUnauthenticated = fn
}

let reauthHandler: (() => Promise<boolean>) | null = null

/**
 * Registered by the app: asked to sign the user in again when a session expires.
 * Resolves true once signed in (the failed request is then retried), false to give up
 * (the user is sent to the login page).
 */
export function setReauthHandler(fn: (() => Promise<boolean>) | null): void {
  reauthHandler = fn
}

export interface ApiEvents {
  /** The server reported the directory as unreachable (503 `directory_unavailable`). */
  onDirectoryUnavailable?: () => void
  /** Build version announced by the server (`X-Heracles-Version`) on a response. */
  onServerVersion?: (version: string) => void
}
const eventListeners = new Set<ApiEvents>()

export function subscribeApiEvents(listener: ApiEvents): () => void {
  eventListeners.add(listener)
  return () => eventListeners.delete(listener)
}

export function resetCsrf(): void {
  csrfToken = null
  csrfPromise = null
}

async function parseError(res: Response): Promise<ApiError> {
  let body: ApiErrorBody['error']
  try {
    const json = (await res.json()) as Partial<ApiErrorBody>
    body = json.error ?? { code: 'internal', message: res.statusText }
  } catch {
    body = { code: 'internal', message: res.statusText || `HTTP ${res.status}` }
  }
  return new ApiError(res.status, body, res.headers.get('X-Request-ID') ?? undefined)
}

async function getCsrf(): Promise<string> {
  if (csrfToken) return csrfToken
  csrfPromise ??= (async () => {
    const res = await fetch(`${API_BASE}/auth/csrf`, { credentials: 'include' })
    if (!res.ok) throw await parseError(res)
    const json = (await res.json()) as CsrfResponse
    csrfToken = json.token
    return json.token
  })().finally(() => {
    csrfPromise = null
  })
  return csrfPromise
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  query?: Record<string, string | number | boolean | null | undefined>
  signal?: AbortSignal
  /** do not trigger the global 401 handler (used for /auth/me and login) */
  silent401?: boolean
}

export function buildQuery(query: RequestOptions['query']): string {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue
    params.set(k, String(v))
  }
  const s = params.toString()
  return s ? `?${s}` : ''
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  return send<T>(path, opts, false)
}

async function send<T>(path: string, opts: RequestOptions, retried: boolean): Promise<T> {
  const method = opts.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') headers['X-CSRF-Token'] = await getCsrf()

  const res = await fetch(`${API_BASE}${path}${buildQuery(opts.query)}`, {
    method,
    headers,
    credentials: 'include',
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    signal: opts.signal,
  })

  const version = res.headers.get('X-Heracles-Version')
  if (version) for (const l of eventListeners) l.onServerVersion?.(version)

  if (!res.ok) {
    const err = await parseError(res)
    if (res.status === 401 && !opts.silent401) {
      if (!retried && reauthHandler && (await reauthHandler())) {
        resetCsrf() // the new session has its own token
        return send<T>(path, opts, true)
      }
      onUnauthenticated?.()
    }
    if (res.status === 503 && err.code === 'directory_unavailable') {
      for (const l of eventListeners) l.onDirectoryUnavailable?.()
    }
    throw err
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

/** URL-encode a DN for use as a path segment. */
export function dnPath(dn: string): string {
  return encodeURIComponent(dn)
}

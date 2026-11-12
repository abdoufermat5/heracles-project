import { ApiError, API_BASE } from '@/api/client'
import type { ApiErrorBody } from '@/api/types'

/**
 * First-run setup API (`/api/v2/setup/*`). It answers before any session exists, so it
 * does not use the CSRF-protected `request()`: every call except `status` carries the
 * one-time `X-Setup-Token` instead.
 */

export interface SetupStatus {
  setup_required: boolean
  version: string
  config_path: string
}

export interface DirectoryInput {
  id: string
  label: string
  uri: string
  starttls: boolean
  ca_file: string | null
  bind_dn: string
  bind_password: string
  base_dn: string
}

export interface DirectoryTestResult {
  ok: boolean
  error: { code: string; message: string } | null
  naming_contexts: string[]
  base_dn_exists: boolean
  can_write: boolean
  schema: { installed: boolean; missing_classes: string[] }
}

export interface SetupPlugin {
  name: string
  label: string
  description: string
  default: boolean
}

export interface SetupPlugins {
  profiles: { id: 'core' | 'all'; plugins: string[] }[]
  plugins: SetupPlugin[]
}

export interface AdminInput {
  uid: string
  given_name: string
  surname: string
  mail: string
  password: string
}

export interface ApplyRequest {
  directory: DirectoryInput
  admin: AdminInput
  plugins: string[]
  public_url: string | null
}

export interface ApplyResult {
  ok: true
  config_path: string
  login_url: string
}

const S = `${API_BASE}/setup`

async function failure(res: Response): Promise<ApiError> {
  try {
    const json = (await res.json()) as Partial<ApiErrorBody>
    if (json.error) return new ApiError(res.status, json.error)
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, { code: 'internal', message: res.statusText || `HTTP ${res.status}` })
}

async function call(path: string, token: string | null, init: { method?: string; body?: unknown } = {}) {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (token) headers['X-Setup-Token'] = token
  if (init.body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(`${S}${path}`, {
    method: init.method ?? 'GET',
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  })
  if (!res.ok) throw await failure(res)
  return res
}

async function json<T>(path: string, token: string, init?: { method?: string; body?: unknown }): Promise<T> {
  return (await (await call(path, token, init)).json()) as T
}

export const setupApi = {
  status: async () => (await (await call('/status', null)).json()) as SetupStatus,
  verifyToken: async (token: string) => {
    await call('/token/verify', token, { method: 'POST', body: { token } })
  },
  testDirectory: (token: string, body: Omit<DirectoryInput, 'id' | 'label'>) =>
    json<DirectoryTestResult>('/directory/test', token, { method: 'POST', body }),
  plugins: (token: string) => json<SetupPlugins>('/plugins', token),
  apply: (token: string, body: ApplyRequest) => json<ApplyResult>('/apply', token, { method: 'POST', body }),
  /** The schema file needs the token header, so it is fetched and handed to the browser as a download. */
  downloadSchema: async (token: string, format: 'ldif' | 'schema') => {
    const res = await call(`/schema?format=${format}`, token)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `heracles.${format}`
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  },
}

// The token lives in memory (and the tab's sessionStorage, to survive a reload), never in localStorage.
const KEY = 'heracles.setup.token'

export function loadToken(): string {
  try {
    return sessionStorage.getItem(KEY) ?? ''
  } catch {
    return ''
  }
}

export function saveToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(KEY, token)
    else sessionStorage.removeItem(KEY)
  } catch {
    /* private mode */
  }
}

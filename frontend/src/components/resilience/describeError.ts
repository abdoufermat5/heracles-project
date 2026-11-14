import type { TFunction } from 'i18next'
import { isApiError } from '@/api/client'

export interface ErrorDescription {
  /** Stable kind, also the key under `resilience.errors`. */
  kind: string
  title: string
  body: string
  /** The server's own wording, shown as a secondary detail when it adds anything. */
  detail?: string
  notFound: boolean
}

const KNOWN = new Set([
  'unauthenticated',
  'forbidden',
  'not_found',
  'validation',
  'locked',
  'conflict',
  'ldap_error',
  'directory_unavailable',
  'reauth_required',
  'second_factor_required',
  'last_second_factor',
  'internal',
])

function kindOf(error: unknown): string {
  if (!isApiError(error)) return 'generic'
  if (KNOWN.has(error.code)) return error.code
  if (error.status === 404) return 'not_found'
  if (error.status === 403) return 'forbidden'
  if (error.status === 401) return 'unauthenticated'
  if (error.status === 409) return 'conflict'
  if (error.status === 422) return 'validation'
  if (error.status === 503) return 'directory_unavailable'
  return error.status >= 500 ? 'internal' : 'generic'
}

/**
 * An error as the person should read it: the API's `code` picks a localized message, and
 * the server's English text is kept only as a secondary detail.
 */
export function describeError(t: TFunction, error: unknown): ErrorDescription {
  const kind = kindOf(error)
  const raw = isApiError(error) ? error.message : error instanceof Error ? error.message : ''
  return {
    kind,
    title: t(`resilience.errors.${kind}.title`),
    body: t(`resilience.errors.${kind}.body`),
    detail: raw || undefined,
    notFound: kind === 'not_found',
  }
}

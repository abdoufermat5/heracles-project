import { useQuery } from '@tanstack/react-query'
import { API_BASE, request } from '@/api/client'

export type LoginMethodId = 'form' | 'http-basic' | 'http-header' | 'cas' | 'oidc'

export interface LoginMethod {
  id: LoginMethodId
  url: string | null
  /** Button text the configuration gives (OpenID Connect). */
  label?: string
}

export interface LoginMethods {
  login_method: LoginMethodId
  methods: LoginMethod[]
}

/** Cookie naming the single sign-on a session was opened through (`cas`, `oidc`), so logout ends it too. */
export const SSO_COOKIE = 'heracles_sso'

export function useLoginMethods() {
  return useQuery({
    queryKey: ['login-methods'],
    queryFn: () => request<LoginMethods>('/auth/methods', { silent401: true }),
    staleTime: 5 * 60_000,
    retry: false,
  })
}

/** Leave the SPA for an identity-provider flow (kept in one function so tests can replace it). */
export function navigateExternal(url: string): void {
  window.location.assign(url)
}

/** Entry URL of a redirect-based method, carrying the post-login target. */
export function methodUrl(method: LoginMethod, next?: string): string {
  const base = method.url ?? `${API_BASE}/auth/${method.id}/login`
  if (!next) return base
  return `${base}${base.includes('?') ? '&' : '?'}next=${encodeURIComponent(next)}`
}

export type SsoMethod = 'cas' | 'oidc'

/** The single sign-on this session was opened through, if any. */
export function ssoCookie(): SsoMethod | null {
  for (const part of document.cookie.split(';')) {
    const [name, value] = part.trim().split('=')
    if (name === SSO_COOKIE && (value === 'cas' || value === 'oidc')) return value
  }
  return null
}

export function hasSsoCookie(): boolean {
  return ssoCookie() !== null
}

/** Ends the Heracles session, then the provider's, and comes back to the login page. */
export function ssoLogoutUrl(method: SsoMethod): string {
  return `${API_BASE}/auth/${method}/logout`
}

export function casLogoutUrl(): string {
  return ssoLogoutUrl('cas')
}

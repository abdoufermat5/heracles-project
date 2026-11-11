import { useQuery } from '@tanstack/react-query'
import { API_BASE, request } from '@/api/client'

export type LoginMethodId = 'form' | 'http-basic' | 'http-header' | 'cas'

export interface LoginMethod {
  id: LoginMethodId
  url: string | null
}

export interface LoginMethods {
  login_method: LoginMethodId
  methods: LoginMethod[]
}

/** Cookie set when the session was opened through CAS (so logout can end the CAS session too). */
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

export function hasSsoCookie(): boolean {
  return document.cookie.split(';').some((c) => c.trim() === `${SSO_COOKIE}=cas`)
}

export function casLogoutUrl(): string {
  return `${API_BASE}/auth/cas/logout`
}

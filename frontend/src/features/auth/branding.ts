import { useQuery } from '@tanstack/react-query'
import { request } from '@/api/client'

/** How the sign-in page presents the organisation (public, from the server settings). */
export interface Branding {
  organization: string
  logo_url: string | null
  tagline: string
}

export function useBranding() {
  return useQuery({
    queryKey: ['branding'],
    queryFn: () => request<Branding>('/branding', { silent401: true }),
    staleTime: 10 * 60_000,
    retry: false,
  })
}

import { useQuery } from '@tanstack/react-query'
import i18n from 'i18next'
import { request } from '@/api/client'
import { MIN_PASSWORD_LENGTH } from '@/lib/password'

/** The rules a new password must meet right now (`GET /auth/password-policy`, public). */
export interface PasswordPolicy {
  min_length: number
}

/** The live policy; until it arrives (or when it cannot be read) the built-in minimum applies. */
export function usePasswordPolicy(): PasswordPolicy {
  const { data } = useQuery({
    queryKey: ['auth', 'password-policy'],
    queryFn: () => request<PasswordPolicy>('/auth/password-policy', { silent401: true }),
    staleTime: 60_000,
    retry: false,
  })
  return data ?? { min_length: MIN_PASSWORD_LENGTH }
}

/** Why `password` cannot be set, or `null`: empty and shorter than the policy are refused. */
export function newPasswordError(password: string, policy: PasswordPolicy): string | null {
  if (password === '') return i18n.t('validation.required')
  if (password.length < policy.min_length)
    return i18n.t('validation.minLength', { count: policy.min_length })
  return null
}

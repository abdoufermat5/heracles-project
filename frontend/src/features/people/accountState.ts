import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/endpoints'
import { qk } from '@/api/hooks'
import type { ObjectListItem } from '@/api/types'

export interface AccountState {
  /** The account is locked (it cannot sign in until unlocked). */
  locked: boolean
  /** False when the entry has no password at all; unknown (true) when the server did not say. */
  passwordSet: boolean
}

/**
 * Lock and password state of one user. The listing is the only place the server reports
 * them (the password itself is write-only), so the account is looked up by its login.
 * Keyed under the user objects: locking or changing a password refreshes it.
 */
export function useAccountState(dn: string) {
  return useQuery({
    queryKey: [...qk.objects('user'), 'accountState', dn],
    queryFn: async (): Promise<AccountState> => {
      const rdn = dn.split(',')[0]?.replace(/^[^=]+=/, '') ?? dn
      const list = await api.listObjects('user', { q: rdn, limit: 10 })
      const found: ObjectListItem | undefined = list.items.find(
        (i) => i.dn.toLowerCase() === dn.toLowerCase(),
      )
      return { locked: found?.locked ?? false, passwordSet: found?.password_set !== false }
    },
    staleTime: 30_000,
  })
}

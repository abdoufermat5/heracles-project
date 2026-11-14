import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import { qk } from '@/api/hooks'
import type { ApiTokenInfo } from '@/api/types'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { RevokeTokenDialog, TokenRow } from './ApiTokensPanel'
import { ReauthDialog } from './ReauthDialog'

const PANEL_HEADER = 'flex h-10 flex-row items-center justify-between border-b px-4 py-0'

/**
 * Someone's API tokens, on their profile, for whoever may lock the account (the server
 * answers 403 otherwise and the panel stays hidden). Revoking needs a recent sign-in.
 */
export function UserApiTokensPanel({ dn }: { dn: string }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const tokens = useQuery({
    queryKey: qk.userApiTokens(dn),
    queryFn: () => api.listUserTokens(dn),
    retry: false,
  })
  const [revoking, setRevoking] = useState<ApiTokenInfo | null>(null)
  const [retry, setRetry] = useState<ApiTokenInfo | null>(null)

  const revoke = useMutation({
    mutationFn: (id: string) => api.revokeToken(id),
    onSuccess: async () => {
      toast.success(t('apiTokens.revoked'))
      await qc.invalidateQueries({ queryKey: qk.userApiTokens(dn) })
    },
    onError: (e, id) => {
      const token = tokens.data?.find((x) => x.id === id) ?? null
      if (isApiError(e) && e.code === 'reauth_required') setRetry(token)
      else toast.error(isApiError(e) ? e.message : t('apiTokens.failed'))
    },
  })

  if (!tokens.data) return null

  return (
    <Card className="gap-0 py-0">
      <CardHeader className={PANEL_HEADER}>
        <CardTitle className="text-lead">{t('apiTokens.userTitle')}</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <p className="px-4 pt-3 text-body text-muted-foreground">{t('apiTokens.userHelp')}</p>
        {tokens.data.length > 0 ? (
          <ul className="mt-3 divide-y border-t text-body" aria-label={t('apiTokens.userTitle')}>
            {tokens.data.map((tok) => (
              <TokenRow key={tok.id} token={tok} busy={revoke.isPending} onRevoke={setRevoking} />
            ))}
          </ul>
        ) : (
          <p className="px-4 py-3 text-body text-muted-foreground">{t('apiTokens.userNone')}</p>
        )}
      </CardContent>
      <RevokeTokenDialog
        token={revoking}
        onCancel={() => setRevoking(null)}
        onConfirm={(tok) => {
          setRevoking(null)
          revoke.mutate(tok.id)
        }}
      />
      <ReauthDialog
        open={retry !== null}
        body={t('apiTokens.reauthRevokeBody')}
        onCancel={() => setRetry(null)}
        onConfirmed={() => {
          const tok = retry
          setRetry(null)
          if (tok) revoke.mutate(tok.id)
        }}
      />
    </Card>
  )
}

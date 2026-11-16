import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, KeyRound, Loader2, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { api } from '@/api/endpoints'
import { qk, useTypes } from '@/api/hooks'
import type { ApiTokenCreated, ApiTokenInfo, ApiTokenRequest, ApiTokenScope } from '@/api/types'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { formatRelative } from '@/features/audit/format'
import { ReauthDialog } from './ReauthDialog'

const PANEL_HEADER = 'flex h-10 flex-row items-center justify-between border-b px-4 py-0'
const SCOPES: ApiTokenScope[] = ['read', 'write', 'admin']
const LIFETIMES = [7, 30, 90, 365]

const when = (seconds: number) => formatRelative(new Date(seconds * 1000).toISOString())

/** One line of a token list: name, scope, types, dates, and a revoke button. */
export function TokenRow({
  token,
  onRevoke,
  busy,
  showCreator = false,
}: {
  token: ApiTokenInfo
  onRevoke: (token: ApiTokenInfo) => void
  busy: boolean
  /** Name who made it (a service account's tokens are made by people). */
  showCreator?: boolean
}) {
  const { t } = useTranslation()
  const facts = [
    t(`apiTokens.scopes.${token.scope}`),
    token.types.length > 0 ? token.types.join(', ') : t('apiTokens.allTypes'),
    ...(token.allowed_ips.length > 0 ? [t('apiTokens.from', { networks: token.allowed_ips.join(', ') })] : []),
    t('apiTokens.expires', { when: when(token.expires_at) }),
    token.last_used_at !== null
      ? t('apiTokens.lastUsed', { when: when(token.last_used_at), ip: token.last_used_ip })
      : t('apiTokens.neverUsed'),
    ...(showCreator ? [t('apiTokens.createdBy', { dn: token.created_by })] : []),
  ]
  return (
    <li className="flex items-center gap-3 px-4 py-2.5">
      <KeyRound className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-foreground">
          {token.name}
          <span className="ml-2 font-mono text-caption text-muted-foreground">{token.id}</span>
        </p>
        <p className="truncate text-caption text-muted-foreground">{facts.join(' · ')}</p>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        disabled={busy}
        onClick={() => onRevoke(token)}
        aria-label={t('apiTokens.revoke', { name: token.name })}
        className="text-destructive hover:bg-destructive-soft hover:text-destructive"
      >
        <Trash2 aria-hidden="true" />
      </Button>
    </li>
  )
}

/** Confirms the revocation of one token (a script using it stops working at once). */
export function RevokeTokenDialog({
  token,
  onCancel,
  onConfirm,
}: {
  token: ApiTokenInfo | null
  onCancel: () => void
  onConfirm: (token: ApiTokenInfo) => void
}) {
  const { t } = useTranslation()
  return (
    <AlertDialog open={token !== null} onOpenChange={(o) => !o && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="text-lead">
            {t('apiTokens.revokeTitle', { name: token?.name ?? '' })}
          </AlertDialogTitle>
          <AlertDialogDescription className="text-body">
            {t('apiTokens.revokeBody')}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('apiTokens.cancel')}</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-white hover:bg-destructive/90"
            onClick={() => token && onConfirm(token)}
          >
            {t('apiTokens.revokeConfirm')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function CreatedSecret({ created, onDone }: { created: ApiTokenCreated; onDone: () => void }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const copy = () => {
    void navigator.clipboard?.writeText(created.secret).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  return (
    <div className="grid gap-4">
      <DialogHeader>
        <DialogTitle className="text-lead">{t('apiTokens.createdTitle')}</DialogTitle>
        <DialogDescription className="text-body">{t('apiTokens.createdBody')}</DialogDescription>
      </DialogHeader>
      <div className="flex items-center gap-2">
        <code
          className="min-w-0 flex-1 break-all rounded-md border bg-muted/50 px-2 py-1.5 font-mono text-caption"
          aria-label={t('apiTokens.secret')}
        >
          {created.secret}
        </code>
        <Button type="button" variant="outline" size="sm" onClick={copy}>
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? t('apiTokens.copied') : t('apiTokens.copy')}
        </Button>
      </div>
      <p className="text-caption text-muted-foreground">
        {t('apiTokens.usage')} <code className="font-mono">Authorization: Bearer …</code>
      </p>
      <DialogFooter>
        <Button type="button" size="sm" onClick={onDone}>
          {t('apiTokens.done')}
        </Button>
      </DialogFooter>
    </div>
  )
}

function CreateTokenDialog({
  open,
  maxDays,
  onClose,
  account,
}: {
  open: boolean
  maxDays: number
  onClose: () => void
  /** The service account the token is for; none: the signed-in person. */
  account?: string
}) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { data: types } = useTypes()
  const lifetimes = LIFETIMES.filter((d) => d <= maxDays)
  const [name, setName] = useState('')
  const [scope, setScope] = useState<ApiTokenScope>('read')
  const [days, setDays] = useState(String(lifetimes.includes(90) ? 90 : (lifetimes.at(-1) ?? maxDays)))
  const [limited, setLimited] = useState(false)
  const [chosen, setChosen] = useState<string[]>([])
  const [networks, setNetworks] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [needsReauth, setNeedsReauth] = useState(false)
  const [created, setCreated] = useState<ApiTokenCreated | null>(null)

  const reset = () => {
    setName('')
    setScope('read')
    setLimited(false)
    setChosen([])
    setNetworks('')
    setFieldErrors({})
    setCreated(null)
  }
  const close = () => {
    reset()
    onClose()
  }

  const create = useMutation({
    mutationFn: () =>
      (account ? (body: ApiTokenRequest) => api.createServiceAccountToken(account, body) : api.createToken)({
        name: name.trim(),
        scope,
        types: limited && scope !== 'admin' ? chosen : [],
        expires_in_days: Number(days),
        allowed_ips: networks
          .split(/[\s,]+/)
          .map((n) => n.trim())
          .filter(Boolean),
      }),
    onSuccess: async (r) => {
      setCreated(r)
      await qc.invalidateQueries({ queryKey: tokensKey(account) })
    },
    onError: (e) => {
      if (isApiError(e) && e.code === 'reauth_required') setNeedsReauth(true)
      else if (isApiError(e) && e.fields) setFieldErrors(e.fields)
      else toast.error(isApiError(e) ? e.message : t('apiTokens.failed'))
    },
  })

  const nameMissing = name.trim() === ''
  const typesMissing = limited && scope !== 'admin' && chosen.length === 0
  const toggle = (type: string, on: boolean) =>
    setChosen((prev) => (on ? [...prev, type] : prev.filter((x) => x !== type)))

  return (
    <>
      <Dialog open={open && !needsReauth} onOpenChange={(o) => !o && close()}>
        <DialogContent className="sm:max-w-lg">
          {created ? (
            <CreatedSecret created={created} onDone={close} />
          ) : (
            <form
              className="grid gap-4"
              onSubmit={(e) => {
                e.preventDefault()
                if (!nameMissing && !typesMissing) create.mutate()
              }}
            >
              <DialogHeader>
                <DialogTitle className="text-lead">{t('apiTokens.createTitle')}</DialogTitle>
                <DialogDescription className="text-body">{t('apiTokens.createBody')}</DialogDescription>
              </DialogHeader>
              <div className="grid gap-1.5">
                <Label htmlFor="token-name">{t('apiTokens.name')}</Label>
                <Input
                  id="token-name"
                  value={name}
                  maxLength={80}
                  autoFocus
                  placeholder={t('apiTokens.namePlaceholder')}
                  onChange={(e) => setName(e.target.value)}
                  aria-invalid={fieldErrors.name ? true : undefined}
                  className="h-8 text-body"
                />
                {fieldErrors.name && <p className="text-caption text-destructive">{fieldErrors.name}</p>}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="grid gap-1.5">
                  <Label htmlFor="token-scope">{t('apiTokens.scope')}</Label>
                  <Select value={scope} onValueChange={(v) => setScope(v as ApiTokenScope)}>
                    <SelectTrigger id="token-scope" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SCOPES.map((s) => (
                        <SelectItem key={s} value={s}>
                          {t(`apiTokens.scopes.${s}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="token-days">{t('apiTokens.lifetime')}</Label>
                  <Select value={days} onValueChange={setDays}>
                    <SelectTrigger id="token-days" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(lifetimes.length > 0 ? lifetimes : [maxDays]).map((d) => (
                        <SelectItem key={d} value={String(d)}>
                          {t('apiTokens.days', { count: d })}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {fieldErrors.expires_in_days && (
                    <p className="text-caption text-destructive">{fieldErrors.expires_in_days}</p>
                  )}
                </div>
              </div>
              <p className="text-caption text-muted-foreground">{t(`apiTokens.scopeHelp.${scope}`)}</p>
              {scope !== 'admin' && (
                <div className="grid gap-2">
                  <div className="flex items-center gap-2">
                    <Switch id="token-limited" checked={limited} onCheckedChange={setLimited} />
                    <Label htmlFor="token-limited">{t('apiTokens.limitTypes')}</Label>
                  </div>
                  {limited && (
                    <ul
                      className="max-h-40 overflow-y-auto rounded-md border p-2 text-body"
                      aria-label={t('apiTokens.types')}
                    >
                      {(types ?? []).map((ty) => (
                        <li key={ty.name} className="flex items-center gap-2 py-0.5">
                          <Checkbox
                            id={`token-type-${ty.name}`}
                            checked={chosen.includes(ty.name)}
                            onCheckedChange={(c) => toggle(ty.name, c === true)}
                          />
                          <Label htmlFor={`token-type-${ty.name}`} className="font-normal">
                            {ty.label} <span className="font-mono text-caption text-muted-foreground">{ty.name}</span>
                          </Label>
                        </li>
                      ))}
                    </ul>
                  )}
                  {(typesMissing || fieldErrors.types) && (
                    <p className="text-caption text-destructive">
                      {fieldErrors.types ?? t('apiTokens.typesMissing')}
                    </p>
                  )}
                </div>
              )}
              <div className="grid gap-1.5">
                <Label htmlFor="token-networks">{t('apiTokens.allowedIps')}</Label>
                <Textarea
                  id="token-networks"
                  value={networks}
                  rows={2}
                  spellCheck={false}
                  placeholder={t('apiTokens.allowedIpsPlaceholder')}
                  onChange={(e) => setNetworks(e.target.value)}
                  aria-invalid={fieldErrors.allowed_ips ? true : undefined}
                  aria-describedby="token-networks-help"
                  className="font-mono text-body"
                />
                <p id="token-networks-help" className="text-caption text-muted-foreground">
                  {t('apiTokens.allowedIpsHelp')}
                </p>
                {fieldErrors.allowed_ips && (
                  <p className="text-caption text-destructive">{fieldErrors.allowed_ips}</p>
                )}
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" size="sm" onClick={close}>
                  {t('apiTokens.cancel')}
                </Button>
                <Button
                  type="submit"
                  size="sm"
                  disabled={nameMissing || typesMissing || create.isPending}
                >
                  {create.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
                  {t('apiTokens.create')}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
      <ReauthDialog
        open={needsReauth}
        body={t('apiTokens.reauthBody')}
        onCancel={() => setNeedsReauth(false)}
        onConfirmed={() => {
          setNeedsReauth(false)
          create.mutate()
        }}
      />
    </>
  )
}

/** The signed-in person's API tokens: create (secret shown once) and revoke. */
/** Cache key of a token list: the signed-in person's, or one service account's. */
const tokensKey = (account?: string) =>
  account ? ([...qk.apiTokens, 'account', account] as const) : qk.apiTokens

/**
 * API tokens of the signed-in person, or with `account` those of a service account (the
 * `dsa` editor shows it; who may set the account's password manages its tokens).
 */
export function ApiTokensPanel({ account }: { account?: string } = {}) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const limits = useQuery({ queryKey: [...qk.apiTokens, 'limits'], queryFn: api.tokenLimits })
  const tokens = useQuery({
    queryKey: tokensKey(account),
    queryFn: () => (account ? api.listServiceAccountTokens(account) : api.listMyTokens()),
  })
  const [creating, setCreating] = useState(false)
  const [revoking, setRevoking] = useState<ApiTokenInfo | null>(null)

  const revoke = useMutation({
    mutationFn: (id: string) =>
      account ? api.revokeServiceAccountToken(account, id) : api.revokeMyToken(id),
    onSuccess: async () => {
      toast.success(t('apiTokens.revoked'))
      await qc.invalidateQueries({ queryKey: tokensKey(account) })
    },
    onError: (e) => toast.error(isApiError(e) ? e.message : t('apiTokens.failed')),
  })

  if (limits.data && !limits.data.enabled) return null

  return (
    <Card id={account ? 'account-api-tokens' : 'portal-api-tokens'} className="gap-0 py-0">
      <CardHeader className={PANEL_HEADER}>
        <CardTitle className="text-lead">{t('apiTokens.title')}</CardTitle>
        <Button type="button" variant="outline" size="sm" onClick={() => setCreating(true)}>
          <Plus aria-hidden="true" />
          {t('apiTokens.new')}
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        <p className="px-4 pt-3 text-body text-muted-foreground">
          {t(account ? 'apiTokens.accountHelp' : 'apiTokens.help')}
        </p>
        {tokens.data && tokens.data.length > 0 ? (
          <ul className="mt-3 divide-y border-t text-body" aria-label={t('apiTokens.title')}>
            {tokens.data.map((tok) => (
              <TokenRow
                key={tok.id}
                token={tok}
                busy={revoke.isPending}
                onRevoke={setRevoking}
                showCreator={account !== undefined}
              />
            ))}
          </ul>
        ) : (
          !tokens.isPending && (
            <p className="px-4 py-3 text-body text-muted-foreground">{t('apiTokens.none')}</p>
          )
        )}
      </CardContent>
      <CreateTokenDialog
        open={creating}
        maxDays={limits.data?.max_lifetime_days ?? 365}
        onClose={() => setCreating(false)}
        account={account}
      />
      <RevokeTokenDialog
        token={revoking}
        onCancel={() => setRevoking(null)}
        onConfirm={(tok) => {
          setRevoking(null)
          revoke.mutate(tok.id)
        }}
      />
    </Card>
  )
}

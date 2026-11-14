import { casLogoutUrl, hasSsoCookie, navigateExternal } from '@/features/auth/sso'
import { dnPath, request, resetCsrf } from './client'
import type {
  ApiTokenCreated,
  ApiTokenInfo,
  ApiTokenLimits,
  ApiTokenRequest,
  CreateObjectRequest,
  Dashboard,
  Directory,
  ListParams,
  LockResponse,
  LoginRequest,
  LoginResponse,
  Me,
  ObjectDetail,
  ObjectList,
  ObjectReference,
  PatchObjectRequest,
  ReauthProof,
  RecoveryCodes,
  RecoveryConfirm,
  RecoveryRequest,
  SecondFactorRequest,
  SessionInfo,
  Snapshot,
  TotpEnrolment,
  TotpStatus,
  TriggerOutput,
  TreeNode,
  TypeDescriptor,
  TypeSummary,
  WebAuthnCredentialInfo,
  WebAuthnOptionsResponse,
  WebAuthnRegisterRequest,
  MyGroup,
  ServerStatus,
} from './types'
import type { CreationOptionsJson, RequestOptionsJson } from '@/lib/webauthn'

export const api = {
  status: () => request<ServerStatus>('/status', { silent401: true }),
  // auth
  directories: () => request<Directory[]>('/directories', { silent401: true }),
  login: async (body: LoginRequest) => {
    const r = await request<LoginResponse>('/auth/login', { method: 'POST', body, silent401: true })
    resetCsrf() // session rotated: fetch a fresh token for the new session
    return r
  },
  secondFactor: (body: SecondFactorRequest) =>
    request<{ status: 'ok' }>('/auth/second-factor', { method: 'POST', body, silent401: true }),
  webauthnOptions: () =>
    request<WebAuthnOptionsResponse<RequestOptionsJson>>('/auth/webauthn/options', {
      method: 'POST',
      silent401: true,
    }),
  listSecurityKeys: () => request<WebAuthnCredentialInfo[]>('/auth/webauthn/credentials'),
  securityKeyOptions: () =>
    request<WebAuthnOptionsResponse<CreationOptionsJson>>('/auth/webauthn/credentials/options', {
      method: 'POST',
    }),
  registerSecurityKey: (body: WebAuthnRegisterRequest) =>
    request<WebAuthnCredentialInfo>('/auth/webauthn/credentials', { method: 'POST', body }),
  deleteSecurityKey: (id: string, confirmDisable = false) =>
    request<undefined>(
      `/auth/webauthn/credentials/${encodeURIComponent(id)}${confirmDisable ? '?confirm_disable=true' : ''}`,
      { method: 'DELETE' },
    ),
  totpStatus: () => request<TotpStatus>('/auth/totp'),
  totpBegin: () => request<TotpEnrolment>('/auth/totp/begin', { method: 'POST' }),
  totpConfirm: (code: string) =>
    request<{ status: 'ok' }>('/auth/totp/confirm', { method: 'POST', body: { code } }),
  totpDisable: (confirmDisable = false) =>
    request<undefined>(`/auth/totp${confirmDisable ? '?confirm_disable=true' : ''}`, {
      method: 'DELETE',
    }),
  generateRecoveryCodes: () => request<RecoveryCodes>('/auth/recovery-codes', { method: 'POST' }),
  /** Confirm the password before a sensitive account change (second factors). */
  reauth: (proof: ReauthProof | string) =>
    request<{ status: 'ok' }>('/auth/reauth', {
      method: 'POST',
      body: typeof proof === 'string' ? { password: proof } : proof,
    }),
  listSessions: () => request<SessionInfo[]>('/auth/sessions'),
  revokeSession: (id: string) =>
    request<undefined>(`/auth/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  revokeOtherSessions: () =>
    request<{ revoked: number }>('/auth/sessions/revoke-others', { method: 'POST' }),
  /** API tokens of the signed-in person (never their secrets). */
  listMyTokens: () => request<ApiTokenInfo[]>('/auth/tokens'),
  tokenLimits: () => request<ApiTokenLimits>('/auth/tokens/limits'),
  /** Needs a recent sign-in (403 `reauth_required` otherwise); the answer holds the secret once. */
  createToken: (body: ApiTokenRequest) =>
    request<ApiTokenCreated>('/auth/tokens', { method: 'POST', body }),
  revokeMyToken: (id: string) =>
    request<undefined>(`/auth/tokens/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  /** Someone's tokens (needs the right to lock their account). */
  listUserTokens: (dn: string) =>
    request<ApiTokenInfo[]>('/tokens', { query: { owner: dn } }),
  /** Revoke someone's token (right to lock their account and a recent sign-in). */
  revokeToken: (id: string) =>
    request<undefined>(`/tokens/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  /** Administrator: sign a user out everywhere (needs the right to lock the account). */
  revokeUserSessions: (dn: string) =>
    request<{ revoked: number; tokens_revoked: number }>(`/users/${dnPath(dn)}/sessions`, {
      method: 'DELETE',
    }),
  logout: async () => {
    if (hasSsoCookie()) {
      // opened through CAS: the server ends our session and the CAS one, then returns to /login
      navigateExternal(casLogoutUrl())
      return
    }
    await request<undefined>('/auth/logout', { method: 'POST' })
    resetCsrf()
  },
  me: () => request<Me>('/auth/me', { silent401: true }),
  requestRecovery: (body: RecoveryRequest) =>
    request<undefined>('/auth/recovery', { method: 'POST', body, silent401: true }),
  confirmRecovery: (body: RecoveryConfirm) =>
    request<{ status: 'ok' }>('/auth/recovery/confirm', { method: 'POST', body, silent401: true }),

  // metadata
  types: () => request<TypeSummary[]>('/types'),
  type: (name: string) => request<TypeDescriptor>(`/types/${encodeURIComponent(name)}`),
  tree: () => request<TreeNode[]>('/tree'),

  // objects
  listObjects: (type: string, p: ListParams, signal?: AbortSignal) =>
    request<ObjectList>(`/objects/${encodeURIComponent(type)}`, {
      query: { ...p },
      signal,
    }),
  getObject: (type: string, dn: string) =>
    request<ObjectDetail>(`/objects/${encodeURIComponent(type)}/${dnPath(dn)}`),
  createObject: (type: string, body: CreateObjectRequest) =>
    request<{ dn: string } & TriggerOutput>(`/objects/${encodeURIComponent(type)}`, {
      method: 'POST',
      body,
    }),
  patchObject: (type: string, dn: string, body: PatchObjectRequest) =>
    request<ObjectDetail>(`/objects/${encodeURIComponent(type)}/${dnPath(dn)}`, {
      method: 'PATCH',
      body,
    }),
  deleteObject: (type: string, dn: string) =>
    request<undefined>(`/objects/${encodeURIComponent(type)}/${dnPath(dn)}`, { method: 'DELETE' }),
  /** Groups the signed-in person belongs to (self-service; no rights on the groups needed). */
  myGroups: () => request<MyGroup[]>('/auth/me/groups'),
  references: (type: string, dn: string) =>
    request<ObjectReference[]>(`/objects/${encodeURIComponent(type)}/${dnPath(dn)}/references`),
  moveObject: (type: string, dn: string, base: string) =>
    request<{ dn: string }>(`/objects/${encodeURIComponent(type)}/${dnPath(dn)}/move`, {
      method: 'POST',
      body: { base },
    }),

  // edit locks
  lockObject: (type: string, dn: string) =>
    request<LockResponse>(`/objects/${encodeURIComponent(type)}/${dnPath(dn)}/lock`, {
      method: 'POST',
    }),
  unlockObject: (type: string, dn: string) =>
    request<undefined>(`/objects/${encodeURIComponent(type)}/${dnPath(dn)}/lock`, {
      method: 'DELETE',
    }),

  // account lock (users)
  lockAccount: (dn: string) => request<undefined>(`/users/${dnPath(dn)}/lock`, { method: 'POST' }),
  unlockAccount: (dn: string) => request<undefined>(`/users/${dnPath(dn)}/unlock`, { method: 'POST' }),

  // snapshots
  snapshots: (type: string, dn: string) =>
    request<Snapshot[]>(`/objects/${encodeURIComponent(type)}/${dnPath(dn)}/snapshots`),
  createSnapshot: (type: string, dn: string, description: string) =>
    request<Snapshot>(`/objects/${encodeURIComponent(type)}/${dnPath(dn)}/snapshots`, {
      method: 'POST',
      body: { description },
    }),
  restoreSnapshot: (id: string) =>
    request<undefined>(`/snapshots/${encodeURIComponent(id)}/restore`, { method: 'POST' }),
  deleteSnapshot: (id: string) =>
    request<undefined>(`/snapshots/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  // dashboard
  dashboard: () => request<Dashboard>('/dashboard'),
}

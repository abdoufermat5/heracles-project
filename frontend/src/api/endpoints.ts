import { casLogoutUrl, hasSsoCookie, navigateExternal } from '@/features/auth/sso'
import { dnPath, request, resetCsrf } from './client'
import type {
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
  PatchObjectRequest,
  RecoveryConfirm,
  RecoveryRequest,
  SecondFactorRequest,
  Snapshot,
  TriggerOutput,
  TreeNode,
  TypeDescriptor,
  TypeSummary,
} from './types'

export const api = {
  // auth
  directories: () => request<Directory[]>('/directories', { silent401: true }),
  login: async (body: LoginRequest) => {
    const r = await request<LoginResponse>('/auth/login', { method: 'POST', body, silent401: true })
    resetCsrf() // session rotated: fetch a fresh token for the new session
    return r
  },
  secondFactor: (body: SecondFactorRequest) =>
    request<{ status: 'ok' }>('/auth/second-factor', { method: 'POST', body, silent401: true }),
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

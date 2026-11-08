/**
 * API calls, types and hooks of the object-management extras: templates, copy,
 * multiple edit, references, snapshots and raw LDIF. See docs/specs/07-objects.md.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { API_BASE, ApiError, dnPath, isApiError, request } from '@/api/client'
import { qk } from '@/api/hooks'
import type { TypeDescriptor, Values } from '@/api/types'

// ── Types ─────────────────────────────────────────────────────────────────

/** Whether the type descriptor says templates can exist for the type (it lists under departments). */
export function supportsTemplates(desc: TypeDescriptor | undefined): boolean {
  return desc !== undefined && 'supports_templates' in desc && desc.supports_templates === true
}

export interface TemplateInfo {
  dn: string
  name: string
  type: string
  /** Department the template lives in. */
  base: string
}

export interface TemplateTab {
  active: boolean
  /** Free text (masks allowed): a string, or a list of strings for multi-valued attributes. */
  values: Record<string, string | string[]>
}

export interface TemplateDetail extends TemplateInfo {
  tabs: Record<string, TemplateTab>
}

export interface TemplateBody {
  name?: string
  base?: string
  tabs: Record<string, { active?: boolean; values: Record<string, string | string[]> }>
}

/** `{ tab: [attribute, ...] }` the user has to provide. */
export type TemplateFields = Record<string, string[]>

/** Resolved values per tab. */
export type ResolvedValues = Record<string, Values>

export interface BulkChange {
  op: 'set' | 'add' | 'remove' | 'clear'
  value?: unknown
}

export type BulkChanges = Record<string, Record<string, BulkChange>>

export interface BulkResult {
  dn: string
  ok: boolean
  error?: string
  code?: string
  fields?: Record<string, string>
}

export interface Reference {
  dn: string
  type: string
  label: string
  attribute: string
}

export interface SnapshotEntry {
  id: string
  description: string | null
  created_at: string | null
  object_dn?: string
  type?: string | null
  source?: string
}

// ── Endpoints ─────────────────────────────────────────────────────────────

const typePath = (type: string) => encodeURIComponent(type)
const objPath = (type: string, dn: string) => `/objects/${typePath(type)}/${dnPath(dn)}`

export const objectsApi = {
  listTemplates: (type: string, base?: string) =>
    request<TemplateInfo[]>(`/types/${typePath(type)}/templates`, { query: { base } }),
  getTemplate: (type: string, dn: string) =>
    request<TemplateDetail>(`/types/${typePath(type)}/templates/${dnPath(dn)}`),
  createTemplate: (type: string, body: TemplateBody) =>
    request<TemplateDetail>(`/types/${typePath(type)}/templates`, { method: 'POST', body }),
  patchTemplate: (type: string, dn: string, body: TemplateBody) =>
    request<TemplateDetail>(`/types/${typePath(type)}/templates/${dnPath(dn)}`, {
      method: 'PATCH',
      body,
    }),
  deleteTemplate: (type: string, dn: string) =>
    request<undefined>(`/types/${typePath(type)}/templates/${dnPath(dn)}`, { method: 'DELETE' }),
  templateFields: (type: string, dn: string) =>
    request<{ fields: TemplateFields }>(`/types/${typePath(type)}/templates/${dnPath(dn)}/fields`),
  previewTemplate: (type: string, dn: string, values: Record<string, Values>) =>
    request<{ tabs: ResolvedValues }>(`/types/${typePath(type)}/templates/${dnPath(dn)}/preview`, {
      method: 'POST',
      body: { values },
    }),

  copyObject: (type: string, dn: string, base: string, values: Record<string, Values>) =>
    request<{ dn: string }>(`${objPath(type, dn)}/copy`, {
      method: 'POST',
      body: { base, values },
    }),

  bulkAttributes: (type: string, dns: string[]) =>
    request<{ attributes: Record<string, string[]> }>(`/objects/${typePath(type)}/_bulk/attributes`, {
      method: 'POST',
      body: { dns },
    }),
  bulkEdit: (type: string, dns: string[], changes: BulkChanges) =>
    request<{ results: BulkResult[] }>(`/objects/${typePath(type)}/_bulk`, {
      method: 'PATCH',
      body: { dns, changes },
    }),

  references: (type: string, dn: string) => request<Reference[]>(`${objPath(type, dn)}/references`),

  snapshots: (type: string, dn: string) => request<SnapshotEntry[]>(`${objPath(type, dn)}/snapshots`),
  createSnapshot: (type: string, dn: string, description: string) =>
    request<SnapshotEntry>(`${objPath(type, dn)}/snapshots`, {
      method: 'POST',
      body: { description },
    }),
  restoreSnapshot: (id: string) =>
    request<unknown>(`/snapshots/${encodeURIComponent(id)}/restore`, { method: 'POST' }),
  deleteSnapshot: (id: string) =>
    request<undefined>(`/snapshots/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  deletedSnapshots: (type: string, base?: string) =>
    request<SnapshotEntry[]>('/snapshots/deleted', { query: { type, base } }),

  /** Raw LDIF of an entry (`text/plain`). */
  objectLdif: async (type: string, dn: string): Promise<string> => {
    const res = await fetch(`${API_BASE}${objPath(type, dn)}/ldif`, {
      credentials: 'include',
      headers: { Accept: 'text/plain' },
    })
    if (!res.ok) {
      throw new ApiError(res.status, {
        code: res.status === 404 ? 'not_found' : 'internal',
        message: res.statusText,
      })
    }
    return res.text()
  },
}

// ── Query keys & hooks ────────────────────────────────────────────────────

export const objectKeys = {
  templates: (type: string, base?: string) => ['templates', type, base ?? null] as const,
  template: (type: string, dn: string) => ['templates', type, 'detail', dn] as const,
  templateFields: (type: string, dn: string) => ['templates', type, 'fields', dn] as const,
  references: (type: string, dn: string) => ['references', type, dn] as const,
  snapshots: (type: string, dn: string) => qk.snapshots(type, dn),
  deleted: (type: string) => ['snapshots', 'deleted', type] as const,
  bulkAttributes: (type: string, dns: string[]) => ['bulkAttributes', type, dns] as const,
  ldif: (type: string, dn: string) => ['ldif', type, dn] as const,
}

export function useTemplates(type: string, base?: string, enabled = true) {
  return useQuery({
    queryKey: objectKeys.templates(type, base),
    queryFn: () => objectsApi.listTemplates(type, base),
    enabled,
  })
}

export function useTemplate(type: string, dn: string | null) {
  return useQuery({
    queryKey: objectKeys.template(type, dn ?? ''),
    queryFn: () => objectsApi.getTemplate(type, dn ?? ''),
    enabled: dn !== null,
  })
}

export function useTemplateFields(type: string, dn: string | null) {
  return useQuery({
    queryKey: objectKeys.templateFields(type, dn ?? ''),
    queryFn: () => objectsApi.templateFields(type, dn ?? ''),
    enabled: dn !== null,
  })
}

export function useTemplateMutations(type: string) {
  const qc = useQueryClient()
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['templates', type] })
  return {
    create: useMutation({
      mutationFn: (body: TemplateBody) => objectsApi.createTemplate(type, body),
      onSuccess: invalidate,
    }),
    patch: useMutation({
      mutationFn: ({ dn, body }: { dn: string; body: TemplateBody }) =>
        objectsApi.patchTemplate(type, dn, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (dn: string) => objectsApi.deleteTemplate(type, dn),
      onSuccess: invalidate,
    }),
  }
}

export function useReferences(type: string, dn: string, enabled = true) {
  return useQuery({
    queryKey: objectKeys.references(type, dn),
    queryFn: () => objectsApi.references(type, dn),
    enabled,
  })
}

export function useSnapshots(type: string, dn: string) {
  return useQuery({
    queryKey: objectKeys.snapshots(type, dn),
    queryFn: () => objectsApi.snapshots(type, dn),
  })
}

export function useSnapshotMutations(type: string, dn: string) {
  const qc = useQueryClient()
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: objectKeys.snapshots(type, dn) })
    void qc.invalidateQueries({ queryKey: ['snapshots', 'deleted'] })
  }
  return {
    create: useMutation({
      mutationFn: (description: string) => objectsApi.createSnapshot(type, dn, description),
      onSuccess: refresh,
    }),
    restore: useMutation({
      mutationFn: (id: string) => objectsApi.restoreSnapshot(id),
      onSuccess: () => {
        refresh()
        void qc.invalidateQueries({ queryKey: qk.objects(type) })
      },
    }),
    remove: useMutation({
      mutationFn: (id: string) => objectsApi.deleteSnapshot(id),
      onSuccess: refresh,
    }),
  }
}

export function useDeletedSnapshots(type: string, enabled: boolean) {
  return useQuery({
    queryKey: objectKeys.deleted(type),
    queryFn: () => objectsApi.deletedSnapshots(type),
    enabled,
  })
}

export function useRestoreSnapshot(type: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => objectsApi.restoreSnapshot(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.objects(type) })
      void qc.invalidateQueries({ queryKey: ['snapshots'] })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
    },
  })
}

export function useBulkAttributes(type: string, dns: string[], enabled: boolean) {
  return useQuery({
    queryKey: objectKeys.bulkAttributes(type, dns),
    queryFn: () => objectsApi.bulkAttributes(type, dns),
    enabled: enabled && dns.length > 0,
  })
}

export function useBulkEdit(type: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ dns, changes }: { dns: string[]; changes: BulkChanges }) =>
      objectsApi.bulkEdit(type, dns, changes),
    onSettled: () => void qc.invalidateQueries({ queryKey: qk.objects(type) }),
  })
}

export function useCopyMove(type: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      items,
      base,
      mode,
    }: {
      items: Array<{ dn: string; values: Record<string, Values> }>
      base: string
      mode: 'copy' | 'move'
    }): Promise<CopyMoveResult[]> => {
      const out: CopyMoveResult[] = []
      for (const item of items) {
        try {
          const r =
            mode === 'copy'
              ? await objectsApi.copyObject(type, item.dn, base, item.values)
              : await moveRequest(type, item.dn, base)
          out.push({ dn: item.dn, ok: true, newDn: r.dn })
        } catch (e) {
          out.push({
            dn: item.dn,
            ok: false,
            error: isApiError(e) ? e.message : String(e),
            fields: isApiError(e) ? e.fields : undefined,
          })
        }
      }
      return out
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: qk.objects(type) })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
    },
  })
}

export interface CopyMoveResult {
  dn: string
  ok: boolean
  newDn?: string
  error?: string
  fields?: Record<string, string>
}

function moveRequest(type: string, dn: string, base: string) {
  return request<{ dn: string }>(`${objPath(type, dn)}/move`, { method: 'POST', body: { base } })
}

/**
 * Raw LDIF from the server. Resolves to `null` when the endpoint is not available
 * (404 / 501), so callers can fall back to a locally built text.
 */
export function useObjectLdif(type: string, dn: string | null, open: boolean) {
  return useQuery({
    queryKey: objectKeys.ldif(type, dn ?? ''),
    queryFn: async () => {
      try {
        return await objectsApi.objectLdif(type, dn ?? '')
      } catch (e) {
        if (isApiError(e) && (e.status === 404 || e.status === 501)) return null
        throw e
      }
    },
    enabled: open && dn !== null,
    staleTime: 0,
    gcTime: 0,
  })
}

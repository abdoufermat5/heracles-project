import { API_BASE, ApiError, buildQuery, request } from '@/api/client'
import type { ApiErrorBody } from '@/api/types'

export interface IoAccess {
  ldif_export: boolean
  ldif_import: boolean
  csv_import: boolean
}

export type LdifScope = 'base' | 'one' | 'sub'

export interface LdifExportParams {
  base: string
  filter: string
  scope: LdifScope
  wrap: number
}

export type LdifAction = 'add' | 'modify' | 'unchanged' | 'exists' | 'error'

export interface LdifImportBody {
  text: string
  overwrite: boolean
  remove_missing: boolean
  dry_run: boolean
}

export interface LdifImportResult {
  index: number
  dn: string
  action: LdifAction
  changes: string[]
  error: string | null
}

export interface LdifImportResponse {
  dry_run: boolean
  summary: Record<LdifAction, number>
  results: LdifImportResult[]
}

export interface CsvOptions {
  text: string
  separator: string
  has_header: boolean
}

export interface CsvParseResponse {
  columns: string[]
  rows: string[][]
  total: number
}

export interface CsvField {
  key: string
  tab: string
  tab_label: string
  attribute: string
  label: string
  kind: string
  required: boolean
  /** The attribute has a default value, so a missing column does not leave it empty. */
  has_default?: boolean
  /** The tab only exists on the object when something fills one of its attributes. */
  tab_optional?: boolean
  multivalued: boolean
}

export interface CsvImportBody extends CsvOptions {
  mapping: { column: number; field: string }[]
  fixed: Record<string, string>
  template: string | null
  base: string | null
}

export interface CsvImportResponse {
  imported: number
  failed: number
  results: { line: number; dn: string | null; error: string | null }[]
}

export interface TemplateInfo {
  dn: string
  name: string
}

/** Query of the LDIF download (a plain GET: the browser sends the session cookie). */
export function ldifExportUrl(p: LdifExportParams): string {
  return `${API_BASE}/ldif/export${buildQuery({
    base: p.base.trim(),
    filter: p.filter.trim(),
    scope: p.scope,
    wrap: p.wrap,
    filename: 'export.ldif',
  })}`
}

/**
 * Fetch the export. The server refuses a bad base or filter (422 with `fields`) and an unknown
 * base (404) before streaming anything: those come back as an `ApiError` the form can show
 * on the field, instead of an error document saved as the download.
 */
export async function ldifExport(p: LdifExportParams): Promise<Blob> {
  const res = await fetch(ldifExportUrl(p), { credentials: 'include' })
  if (!res.ok) {
    let body: ApiErrorBody['error']
    try {
      const json = (await res.json()) as Partial<ApiErrorBody>
      body = json.error ?? { code: 'internal', message: res.statusText }
    } catch {
      body = { code: 'internal', message: res.statusText || `HTTP ${res.status}` }
    }
    throw new ApiError(res.status, body, res.headers.get('X-Request-ID') ?? undefined)
  }
  return await res.blob()
}

export const ioApi = {
  access: () => request<IoAccess>('/ldapmanager/access'),
  ldifImport: (body: LdifImportBody) =>
    request<LdifImportResponse>('/ldif/import', { method: 'POST', body }),
  csvParse: (body: CsvOptions) =>
    request<CsvParseResponse>('/csv/parse', { method: 'POST', body }),
  csvFields: (type: string, template?: string | null) =>
    request<CsvField[]>(`/csv/${encodeURIComponent(type)}/fields`, {
      query: { template: template ?? undefined },
    }),
  csvImport: (type: string, body: CsvImportBody) =>
    request<CsvImportResponse>(`/csv/${encodeURIComponent(type)}/import`, {
      method: 'POST',
      body,
    }),
  /** Templates of a type; the endpoint may not exist yet (empty list then). */
  templates: async (type: string): Promise<TemplateInfo[]> => {
    try {
      const body = await request<TemplateInfo[] | { items?: TemplateInfo[]; templates?: TemplateInfo[] }>(
        `/types/${encodeURIComponent(type)}/templates`,
      )
      return Array.isArray(body) ? body : (body.items ?? body.templates ?? [])
    } catch {
      return []
    }
  },
}

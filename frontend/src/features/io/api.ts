import { API_BASE, buildQuery, request } from '@/api/client'

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

/** URL of the LDIF download (a plain GET: the browser sends the session cookie). */
export function ldifExportUrl(p: LdifExportParams): string {
  return `${API_BASE}/ldif/export${buildQuery({
    base: p.base.trim(),
    filter: p.filter.trim(),
    scope: p.scope,
    wrap: p.wrap,
    filename: 'export.ldif',
  })}`
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

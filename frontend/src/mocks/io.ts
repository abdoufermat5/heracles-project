import { http, HttpResponse, type HttpHandler } from 'msw'
import type { TabState } from '@/api/types'
import { BASE_DN, db, departments } from './db'

// --- P3 compat ---
const B = '/api/v2'

const SEPARATORS: Record<string, string> = { ',': ',', ';': ';', tab: '\t', '|': '|' }

const CSV_FIELDS = [
  { tab: 'main', attribute: 'uid', label: 'Login', kind: 'string', required: true, multivalued: false },
  { tab: 'main', attribute: 'givenName', label: 'First name', kind: 'string', required: true, multivalued: false },
  { tab: 'main', attribute: 'sn', label: 'Last name', kind: 'string', required: true, multivalued: false },
  { tab: 'main', attribute: 'mail', label: 'Email', kind: 'string', required: true, multivalued: false },
].map((f) => ({
  ...f,
  key: `${f.tab}.${f.attribute}`,
  tab_label: 'Identity',
}))

function parseCsv(text: string, separator: string, hasHeader: boolean) {
  const delimiter = SEPARATORS[separator] ?? ','
  const lines = text
    .split(/\r?\n/)
    .map((raw, i) => ({ raw, line: i + 1 }))
    .filter((l) => l.raw.trim() !== '')
  const cells = lines.map((l) => l.raw.split(delimiter).map((c) => c.trim()))
  const first = cells[0] ?? []
  const columns = hasHeader ? first : first.map((_, i) => `#${i + 1}`)
  return {
    columns,
    rows: hasHeader ? cells.slice(1) : cells,
    lines: hasHeader ? lines.slice(1).map((l) => l.line) : lines.map((l) => l.line),
  }
}

function err(status: number, code: string, message: string) {
  return HttpResponse.json({ error: { code, message } }, { status })
}

export const ioHandlers: HttpHandler[] = [
  http.get(`${B}/auth/methods`, () =>
    HttpResponse.json({ login_method: 'form', methods: [{ id: 'form', url: null }] }),
  ),

  http.get(`${B}/ldapmanager/access`, () =>
    db.me()
      ? HttpResponse.json({ ldif_export: true, ldif_import: true, csv_import: true })
      : err(401, 'unauthenticated', 'Authentication required'),
  ),

  // object templates are provided by another module: not available in the mock
  http.get(`${B}/types/:type/templates`, () => err(404, 'not_found', 'No templates')),

  http.post(`${B}/ldif/import`, async ({ request }) => {
    const body = (await request.json()) as {
      text: string
      overwrite: boolean
      remove_missing: boolean
      dry_run: boolean
    }
    const blocks = body.text.split(/\r?\n\r?\n/).filter((b) => b.trim() !== '')
    const summary = { add: 0, modify: 0, unchanged: 0, exists: 0, error: 0 }
    const results = blocks.map((block, index) => {
      const dn = /^dn:\s*(.+)$/im.exec(block)?.[1]?.trim() ?? ''
      const known = db.get(dn) !== undefined
      let action: keyof typeof summary = 'add'
      let error: string | null = null
      if (!dn) {
        action = 'error'
        error = 'Entry without a DN'
      } else if (!/^objectClass:/im.test(block)) {
        action = 'error'
        error = 'Entry without objectClass'
      } else if (known) action = body.overwrite ? 'modify' : 'exists'
      summary[action] += 1
      return { index: index + 1, dn, action, changes: action === 'modify' ? ['description'] : [], error }
    })
    return HttpResponse.json({ dry_run: body.dry_run, summary, results })
  }),

  http.post(`${B}/csv/parse`, async ({ request }) => {
    const body = (await request.json()) as { text: string; separator: string; has_header: boolean }
    const parsed = parseCsv(body.text, body.separator, body.has_header)
    return HttpResponse.json({
      columns: parsed.columns,
      rows: parsed.rows.slice(0, 10),
      total: parsed.rows.length,
    })
  }),

  http.get(`${B}/csv/:type/fields`, ({ params }) =>
    params.type === 'user' ? HttpResponse.json(CSV_FIELDS) : HttpResponse.json([]),
  ),

  http.post(`${B}/csv/:type/import`, async ({ request, params }) => {
    const type = String(params.type)
    const desc = db.descriptor(type)
    if (!desc) return err(404, 'not_found', 'Unknown type')
    const body = (await request.json()) as {
      text: string
      separator: string
      has_header: boolean
      mapping: { column: number; field: string }[]
      fixed: Record<string, string>
    }
    const parsed = parseCsv(body.text, body.separator, body.has_header)
    const results = parsed.rows.map((row, i) => {
      const values: Record<string, string> = { ...body.fixed }
      for (const m of body.mapping) values[m.field] = row[m.column] ?? ''
      const base = departments[0]?.dn ?? BASE_DN
      const main: TabState = { active: true, values: { base } }
      for (const [key, value] of Object.entries(values)) {
        if (key.startsWith('main.') && value !== '') main.values[key.slice(5)] = value
      }
      const tabs = { main }
      const errors = db.validate(desc, tabs)
      const line = parsed.lines[i] ?? i + 1
      const first = Object.entries(errors)[0]
      if (first) return { line, dn: null, error: `${first[0]}: ${first[1]}` }
      const rec = db.create(type, base, tabs)
      return { line, dn: rec.dn, error: null }
    })
    const imported = results.filter((r) => r.error === null).length
    return HttpResponse.json({ imported, failed: results.length - imported, results })
  }),
]

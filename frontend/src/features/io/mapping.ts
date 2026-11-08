import type { CsvField } from './api'

/** Pre-select the field whose attribute name or label equals the column header. */
export function guessMapping(columns: string[], fields: CsvField[]): Record<number, string> {
  const out: Record<number, string> = {}
  const used = new Set<string>()
  columns.forEach((name, index) => {
    const wanted = name.trim().toLowerCase()
    const hit = fields.find(
      (f) =>
        !used.has(f.key) &&
        (f.attribute.toLowerCase() === wanted || f.label.toLowerCase() === wanted),
    )
    if (hit) {
      out[index] = hit.key
      used.add(hit.key)
    }
  })
  return out
}

import type { ColumnDescriptor, ObjectListItem } from '@/api/types'

/**
 * One CSV cell. Values starting with a character a spreadsheet reads as a formula
 * (`=`, `+`, `-`, `@`, tab, carriage return) are prefixed with an apostrophe, so
 * a directory value cannot run as a formula when the file is opened.
 */
export function escapeCsvField(val: unknown): string {
  if (val === null || val === undefined) return ''
  let str = Array.isArray(val) ? val.join('; ') : String(val)
  if (/^[=+\-@\t\r]/.test(str)) str = `'${str}`
  if (str.includes(',') || str.includes('"') || str.includes('\n') || str.includes('\r')) {
    return `"${str.replace(/"/g, '""')}"`
  }
  return str
}

export function exportToCsv(
  filename: string,
  columns: ColumnDescriptor[],
  rows: ObjectListItem[],
): void {
  const headerLabels = ['DN', ...columns.map((c) => c.label)]

  const csvRows: string[] = [headerLabels.map(escapeCsvField).join(',')]

  for (const row of rows) {
    const line = [
      escapeCsvField(row.dn),
      ...columns.map((c) => escapeCsvField(row.values[c.key])),
    ]
    csvRows.push(line.join(','))
  }

  const blob = new Blob([csvRows.join('\r\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.setAttribute('download', filename.endsWith('.csv') ? filename : `${filename}.csv`)
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

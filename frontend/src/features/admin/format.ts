/** Local date and time of an ISO timestamp, or an em dash when absent or unreadable. */
export function formatDateTime(iso: string | null | undefined, locale: string): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' })
}

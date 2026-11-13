// Characters a URL parser silently drops or rewrites (tab, newline, backslash → slash): `/\t/host`
// and `/\host` would both turn into the protocol-relative `//host`.
// eslint-disable-next-line no-control-regex
const UNSAFE_PATH_CHARS = /[\u0000-\u001f\u007f\\]/

/** Only same-origin absolute paths are accepted as post-login targets (no open redirect). */
export function safeRedirect(v: unknown): string | undefined {
  return typeof v === 'string' && v.startsWith('/') && !v.startsWith('//') && !UNSAFE_PATH_CHARS.test(v)
    ? v
    : undefined
}

/**
 * A value that came from the directory, made fit for an `href`: a same-origin path, or an
 * http(s) URL (a bare host name gets `https://`). Anything else (`javascript:`, `data:`, ...)
 * yields `null`: show it as text, never as a link.
 */
export function safeLinkHref(raw: string): string | null {
  const value = raw.trim()
  if (value.startsWith('/')) return safeRedirect(value) ?? null
  const candidate = /^https?:\/\//i.test(value) ? value : `https://${value}`
  try {
    const url = new URL(candidate)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}

/** A short device name out of a User-Agent header ("Firefox on Linux"); empty when unknown. */
export function deviceName(userAgent: string): string {
  if (!userAgent) return ''
  const browser =
    /Edg\//.test(userAgent) ? 'Edge'
    : /OPR\/|Opera/.test(userAgent) ? 'Opera'
    : /Firefox\//.test(userAgent) ? 'Firefox'
    : /Chrome\//.test(userAgent) ? 'Chrome'
    : /Safari\//.test(userAgent) ? 'Safari'
    : ''
  const system =
    /Windows/.test(userAgent) ? 'Windows'
    : /Android/.test(userAgent) ? 'Android'
    : /iPhone|iPad|iOS/.test(userAgent) ? 'iOS'
    : /Mac OS X|Macintosh/.test(userAgent) ? 'macOS'
    : /Linux/.test(userAgent) ? 'Linux'
    : ''
  if (browser && system) return `${browser} on ${system}`
  return browser || system || userAgent.slice(0, 60)
}

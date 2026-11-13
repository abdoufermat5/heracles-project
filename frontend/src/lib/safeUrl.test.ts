import { safeLinkHref, safeRedirect } from './safeUrl'

describe('safeRedirect', () => {
  it('keeps same-origin absolute paths', () => {
    expect(safeRedirect('/types/user?filter=x#top')).toBe('/types/user?filter=x#top')
    expect(safeRedirect('/')).toBe('/')
  })

  it('refuses everything that can leave the origin', () => {
    for (const bad of [
      '//evil.example',
      '/\\evil.example',
      '/\t/evil.example',
      '/\n/evil.example',
      '/\r/evil.example',
      'https://evil.example',
      'javascript:alert(1)',
      'evil',
      '',
      undefined,
      42,
    ]) {
      expect(safeRedirect(bad)).toBeUndefined()
    }
  })
})

describe('safeLinkHref', () => {
  it('accepts http(s) URLs, bare hosts and same-origin paths', () => {
    expect(safeLinkHref('https://example.org/terms')).toBe('https://example.org/terms')
    expect(safeLinkHref('HTTP://example.org')).toBe('http://example.org/')
    expect(safeLinkHref('example.org')).toBe('https://example.org/')
    expect(safeLinkHref('httpbin.org')).toBe('https://httpbin.org/')
    expect(safeLinkHref('/terms')).toBe('/terms')
  })

  it('refuses script and data URLs, and protocol-relative paths', () => {
    for (const bad of [
      'javascript:alert(1)',
      ' JaVaScRiPt:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:x',
      '//evil.example',
      '/\\evil.example',
      '',
    ]) {
      expect(safeLinkHref(bad)).toBeNull()
    }
  })
})

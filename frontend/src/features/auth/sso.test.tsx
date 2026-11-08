import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, vi } from 'vitest'
import { api } from '@/api/endpoints'
import { server } from '@/mocks/server'
import { renderApp } from '@/test/utils'
import { casLogoutUrl, hasSsoCookie, methodUrl, navigateExternal, SSO_COOKIE } from './sso'

vi.mock('./sso', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./sso')>()),
  navigateExternal: vi.fn(),
}))

function methods(login_method: string, ids: string[]) {
  server.use(
    http.get('/api/v2/auth/methods', () =>
      HttpResponse.json({
        login_method,
        methods: ids.map((id) => ({
          id,
          url: id === 'form' ? null : `/api/v2/auth/${id === 'cas' ? 'cas/login' : `login/${id.replace('http-', '')}`}`,
        })),
      }),
    ),
  )
}

afterEach(() => {
  document.cookie = `${SSO_COOKIE}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`
  vi.mocked(navigateExternal).mockClear()
})

describe('login page entry points', () => {
  it('shows only the form when it is the sole method', async () => {
    renderApp('/login')
    expect(await screen.findByLabelText('Username')).toBeInTheDocument()
    expect(screen.queryByTestId('sso-entry')).not.toBeInTheDocument()
  })

  it('shows the single sign-on button as the primary action next to the form', async () => {
    methods('cas', ['form', 'cas'])
    renderApp('/login?redirect=%2Ftypes%2Fuser')
    const link = await screen.findByRole('link', { name: 'Sign in with single sign-on' })
    expect(link).toHaveAttribute('href', '/api/v2/auth/cas/login?next=%2Ftypes%2Fuser')
    expect(link).toHaveAttribute('data-variant', 'default')
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('offers the browser-credentials method as a secondary action', async () => {
    methods('form', ['form', 'http-basic'])
    renderApp('/login')
    const link = await screen.findByRole('link', { name: 'Sign in with browser credentials' })
    expect(link).toHaveAttribute('data-variant', 'outline')
  })

  it('explains a failed single sign-on', async () => {
    methods('cas', ['form', 'cas'])
    renderApp('/login?sso_error=1')
    expect(await screen.findByRole('alert')).toHaveTextContent('Single sign-on failed')
  })

  it('keeps the form usable when the methods cannot be loaded', async () => {
    server.use(http.get('/api/v2/auth/methods', () => HttpResponse.error()))
    renderApp('/login')
    expect(await screen.findByLabelText('Username')).toBeInTheDocument()
    expect(screen.queryByTestId('sso-entry')).not.toBeInTheDocument()
  })
})

describe('helpers', () => {
  it('builds entry URLs', () => {
    expect(methodUrl({ id: 'cas', url: '/api/v2/auth/cas/login' })).toBe('/api/v2/auth/cas/login')
    expect(methodUrl({ id: 'cas', url: '/x?a=1' }, '/y')).toBe('/x?a=1&next=%2Fy')
    expect(methodUrl({ id: 'oidc', url: null }, '/y')).toBe('/api/v2/auth/oidc/login?next=%2Fy')
  })

  it('logs out of CAS too when the session was opened through it', async () => {
    const go = vi.mocked(navigateExternal)
    document.cookie = `${SSO_COOKIE}=cas; path=/`
    expect(hasSsoCookie()).toBe(true)
    await api.logout()
    expect(go).toHaveBeenCalledWith(casLogoutUrl())
  })

  it('uses the regular logout endpoint otherwise', async () => {
    const go = vi.mocked(navigateExternal)
    expect(hasSsoCookie()).toBe(false)
    let called = false
    server.use(
      http.get('/api/v2/auth/csrf', () => HttpResponse.json({ token: 't' })),
      http.post('/api/v2/auth/logout', () => {
        called = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    await api.logout()
    expect(called).toBe(true)
    expect(go).not.toHaveBeenCalled()
  })
})

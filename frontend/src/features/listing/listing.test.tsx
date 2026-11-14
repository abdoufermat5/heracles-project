import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import i18n from '@/i18n'
import { db } from '@/mocks/db'
import { server } from '@/mocks/server'
import { must, renderApp, signIn } from '@/test/utils'

describe('listing page', () => {
  it('renders columns for users and the total count', async () => {
    signIn()
    renderApp('/types/user')
    expect(await screen.findByRole('columnheader', { name: /Person/ })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /Email/ })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /Status/ })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /Department/ })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /Groups/ })).toBeInTheDocument()
    expect(await screen.findByText(/1–25 of 200/)).toBeInTheDocument()
    expect(screen.getAllByRole('row').length).toBeGreaterThan(5)
  })

  it('searches server-side with q', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    const target = must(db.all('user')[7])
    const uid = String(target.tabs.main?.values.uid)
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search' }), uid)
    await waitFor(() => expect(screen.queryByText(/1–25 of 200/)).not.toBeInTheDocument())
    expect((await screen.findAllByText(uid)).length).toBeGreaterThan(0)
  })

  it('sorts via the server when a header is clicked', async () => {
    signIn()
    const seen: string[] = []
    server.events.on('request:start', ({ request }) => {
      const u = new URL(request.url)
      if (u.pathname.endsWith('/objects/user')) seen.push(u.search)
    })
    renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    await userEvent.click(screen.getByRole('button', { name: /Person/ }))
    await waitFor(() => expect(seen.some((s) => s.includes('order=asc'))).toBe(true))
  })

  it('shows the locked badge and a bulk actions bar on selection', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    expect((await screen.findAllByText('Locked')).length).toBeGreaterThan(0)
    const rows = screen.getAllByRole('row')
    await userEvent.click(within(must(rows[1])).getByRole('checkbox'))
    const bar = await screen.findByRole('region', { name: 'Bulk actions' })
    expect(within(bar).getByText('1 selected')).toBeInTheDocument()
    expect(within(bar).getByRole('button', { name: /Lock$/ })).toBeInTheDocument()
    expect(within(bar).getByRole('button', { name: /Delete/ })).toBeInTheDocument()
  })

  it('shows the empty and error states', async () => {
    signIn()
    server.use(http.get('/api/v2/objects/group', () => HttpResponse.json({ items: [], next_cursor: null, total: 0 })))
    const { unmount } = renderApp('/types/group')
    expect(await screen.findByText('Nothing here yet')).toBeInTheDocument()
    unmount()

    server.use(
      http.get('/api/v2/objects/role', () =>
        HttpResponse.json({ error: { code: 'ldap_error', message: 'Directory down' } }, { status: 502 }),
      ),
    )
    renderApp('/types/role')
    expect(await screen.findByRole('alert')).toHaveTextContent('Directory down')
  })

  it('shows a calm error state when the LDAP filter is refused', async () => {
    signIn()
    server.use(
      http.get('/api/v2/objects/group', () =>
        HttpResponse.json({ error: { code: 'invalid_filter', message: 'Unknown attribute: nope' } }, { status: 400 }),
      ),
    )
    renderApp('/types/group?ldap=' + encodeURIComponent('(nope=1)'))
    expect(await screen.findByText('This filter could not be run')).toBeInTheDocument()
    expect(screen.queryByText('Try a different search term')).not.toBeInTheDocument()
    expect(screen.getAllByText(/Unknown attribute: nope/).length).toBeGreaterThan(0)
    const state = screen.getByText('This filter could not be run').closest('[role="status"]') as HTMLElement
    expect(within(state).getByRole('button', { name: 'Clear filter' })).toBeInTheDocument()
  })

  it('paginates results with real pagination', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    expect(screen.getByRole('navigation', { name: 'Pagination' })).toBeInTheDocument()
    expect(screen.getByText(/1–25 of 200/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }))
    expect(await screen.findByText(/26–50 of 200/)).toBeInTheDocument()
  })

  it('clears search when clear button is clicked', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    const input = screen.getByRole('searchbox', { name: 'Search' })
    await userEvent.type(input, 'testquery')
    expect(input).toHaveValue('testquery')
    const clearBtn = await screen.findByRole('button', { name: 'Clear search' })
    await userEvent.click(clearBtn)
    expect(input).toHaveValue('')
  })

  it('opens and confirms bulk delete dialog listing selected objects', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    const rows = screen.getAllByRole('row')
    await userEvent.click(within(must(rows[1])).getByRole('checkbox'))

    const bar = await screen.findByRole('region', { name: 'Bulk actions' })
    await userEvent.click(within(bar).getByRole('button', { name: /Delete/ }))

    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText('Delete 1 item?')).toBeInTheDocument()
    expect(within(dialog).getByText(/permanently deleted/)).toBeInTheDocument()

    // Cancel closes dialog
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  })

  it('shows no matches empty state with clear search action', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    const input = screen.getByRole('searchbox', { name: 'Search' })
    await userEvent.type(input, 'nonexistent_user_12345')
    expect(await screen.findByText('No matching results')).toBeInTheDocument()
    const clearBtns = screen.getAllByRole('button', { name: 'Clear search' })
    await userEvent.click(clearBtns[0]!)
    await waitFor(() => expect(input).toHaveValue(''))
    expect(await screen.findByText(/1–25 of 200/)).toBeInTheDocument()
  })

  it('shows permission denied state for 403 responses', async () => {
    signIn()
    server.use(
      http.get('/api/v2/objects/user', () =>
        HttpResponse.json(
          { error: { code: 'forbidden', message: 'Not allowed' } },
          { status: 403 },
        ),
      ),
    )
    renderApp('/types/user')
    expect(await screen.findByText('Access denied')).toBeInTheDocument()
  })

  it('toggles the preview panel on wide screens', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    expect(screen.queryByRole('complementary', { name: 'Preview' })).not.toBeInTheDocument()

    const toggleBtn = screen.getByRole('button', { name: 'Preview' })
    await userEvent.click(toggleBtn)

    const preview = await screen.findByRole('complementary', { name: 'Preview' })
    expect(preview).toBeInTheDocument()
    expect(within(preview).getByRole('link', { name: 'Open' })).toBeInTheDocument()

    const closeBtn = within(preview).getByRole('button', { name: 'Close preview' })
    await userEvent.click(closeBtn)
    await waitFor(() =>
      expect(screen.queryByRole('complementary', { name: 'Preview' })).not.toBeInTheDocument(),
    )
  })

  it('toggles density between comfortable and compact', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    // compact is the default for console users
    const densityBtn = screen.getByRole('button', { name: 'Comfortable' })
    await userEvent.click(densityBtn)
    expect(screen.getByRole('button', { name: 'Compact' })).toBeInTheDocument()
  })

  it('keeps the view in the URL and restores it from a shared link', async () => {
    signIn()
    const { history, unmount } = renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    await userEvent.click(screen.getByRole('button', { name: /Person/ }))
    await waitFor(() => expect(history.location.search).toContain('sort='))
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }))
    await waitFor(() => expect(history.location.search).toContain('page=2'))
    const url = history.location.href
    unmount()
    // a pasted link reopens on the same page and sort
    renderApp(url)
    expect(await screen.findByText(/26–50 of 200/)).toBeInTheDocument()
  })

  it('applies a raw LDAP filter and explains a server refusal once', async () => {
    signIn()
    const seen: string[] = []
    server.events.on('request:start', ({ request }) => {
      const u = new URL(request.url)
      if (u.pathname.endsWith('/objects/user')) seen.push(u.search)
    })
    renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    await userEvent.click(screen.getByRole('button', { name: 'Advanced filter' }))
    const input = screen.getByRole('textbox', { name: 'Advanced filter' })
    await userEvent.type(input, '(nosuchattr=1){Enter}')
    expect(await screen.findByText('This filter could not be run')).toBeInTheDocument()
    expect(screen.getAllByText(/'nosuchattr'/)).toHaveLength(1)
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(seen.some((s) => s.includes('filter=%28nosuchattr'))).toBe(true)
    await userEvent.clear(input)
    await userEvent.type(input, '(uid=*){Enter}')
    await waitFor(() => expect(screen.queryByText('This filter could not be run')).not.toBeInTheDocument())
  })

  it('moves the row cursor with j/k and selects with x', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText(/1–25 of 200/)
    const table = screen.getByLabelText(/j\/k move/)
    table.focus()
    await userEvent.keyboard('jjkx')
    const bar = await screen.findByRole('region', { name: 'Bulk actions' })
    expect(within(bar).getByText('1 selected')).toBeInTheDocument()
  })
})


describe('server labels in French', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('translates the heading, the navigation entries and the create button', async () => {
    signIn()
    await i18n.changeLanguage('fr')
    renderApp('/types/user')

    expect(await screen.findByRole('heading', { name: 'Utilisateurs' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /Nouvel utilisateur/ })).toBeInTheDocument()

    const nav = await screen.findByRole('navigation', { name: 'Navigation principale' })
    expect(within(nav).getByRole('link', { name: /Utilisateurs/ })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: /Groupes/ })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: /Départements/ })).toBeInTheDocument()
  })

  it('translates the column headers and keeps the range and plural wording', async () => {
    signIn()
    await i18n.changeLanguage('fr')
    renderApp('/types/group')

    await screen.findByText(/^\d+–\d+ sur \d+$/)
    expect(screen.getByRole('columnheader', { name: /Nom/ })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /Description/ })).toBeInTheDocument()
    // The en dash range and the count plural rule are untouched by the label layer.
    expect(screen.getByText(/^\d+–\d+ sur \d+$/)).toBeInTheDocument()
  })
})

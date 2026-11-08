import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { db } from '@/mocks/db'
import { server } from '@/mocks/server'
import { must, renderApp, signIn } from '@/test/utils'

describe('listing page', () => {
  it('renders columns from the type descriptor and the total count', async () => {
    signIn()
    renderApp('/types/user')
    expect(await screen.findByRole('columnheader', { name: /Login/ })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /Email/ })).toBeInTheDocument()
    expect(await screen.findByText('200 items')).toBeInTheDocument()
    expect(screen.getAllByRole('row').length).toBeGreaterThan(5)
  })

  it('searches server-side with q', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText('200 items')
    const target = must(db.all('user')[7])
    const uid = String(target.tabs.main?.values.uid)
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search' }), uid)
    await waitFor(() => expect(screen.queryByText('200 items')).not.toBeInTheDocument())
    expect(await screen.findByRole('link', { name: uid })).toBeInTheDocument()
  })

  it('sorts via the server when a header is clicked', async () => {
    signIn()
    const seen: string[] = []
    server.events.on('request:start', ({ request }) => {
      const u = new URL(request.url)
      if (u.pathname.endsWith('/objects/user')) seen.push(u.search)
    })
    renderApp('/types/user')
    await screen.findByText('200 items')
    await userEvent.click(screen.getByRole('button', { name: /Name/ }))
    await waitFor(() => expect(seen.some((s) => s.includes('sort=cn') && s.includes('order=asc'))).toBe(true))
  })

  it('shows the locked badge and a bulk actions bar on selection', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText('200 items')
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

  it('loads more results with the cursor', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText('200 items')
    await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    expect(await screen.findByText(/Showing 100 of 200/)).toBeInTheDocument()
  })

  it('clears search when clear button is clicked', async () => {
    signIn()
    renderApp('/types/user')
    await screen.findByText('200 items')
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
    await screen.findByText('200 items')
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
    await screen.findByText('200 items')
    const input = screen.getByRole('searchbox', { name: 'Search' })
    await userEvent.type(input, 'nonexistent_user_12345')
    expect(await screen.findByText('No matching results')).toBeInTheDocument()
    const clearBtns = screen.getAllByRole('button', { name: 'Clear search' })
    await userEvent.click(clearBtns[0]!)
    await waitFor(() => expect(input).toHaveValue(''))
    expect(await screen.findByText('200 items')).toBeInTheDocument()
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
    await screen.findByText('200 items')
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
    await screen.findByText('200 items')
    const densityBtn = screen.getByRole('button', { name: 'Compact' })
    await userEvent.click(densityBtn)
    expect(screen.getByRole('button', { name: 'Comfortable' })).toBeInTheDocument()
  })
})


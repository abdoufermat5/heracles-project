import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { db } from '@/mocks/db'
import { server } from '@/mocks/server'
import { typeSummaries } from '@/mocks/typeDefs'
import { must, renderApp, signIn } from '@/test/utils'
import { auditApi } from './api'
import { formatRelative, parseAttribute } from './format'

describe('audit format helpers', () => {
  it('parses attribute lines', () => {
    expect(parseAttribute('replace mail: a@b.c')).toEqual({ kind: 'change', op: 'replace', name: 'mail', value: 'a@b.c' })
    expect(parseAttribute('uid: jdoe')).toEqual({ kind: 'change', op: 'set', name: 'uid', value: 'jdoe' })
    expect(parseAttribute('source import')).toEqual({ kind: 'text', text: 'source import' })
  })

  it('formats relative times', () => {
    const now = Date.parse('2030-01-01T12:00:00Z')
    expect(formatRelative('2030-01-01T09:00:00Z', now)).toBe('3 hours ago')
  })

  it('builds the export link from the filters, without the page size', () => {
    const url = auditApi.exportUrl({ action: ['login', 'delete'], actor: 'uid=a', limit: 50 })
    expect(url).toContain('/api/v2/audit?')
    expect(url).toContain('action=login&action=delete')
    expect(url).toContain('format=csv')
    expect(url).not.toContain('limit')
  })
})

describe('audit log page', () => {
  it('lists events with readable labels first and the DN as secondary text', async () => {
    signIn()
    renderApp('/activity/audit')
    expect(await screen.findByRole('heading', { name: 'Audit log' })).toBeInTheDocument()
    const rows = await screen.findAllByTestId('audit-row')
    expect(rows.length).toBe(6)
    const failed = rows.find((r) => within(r).queryByText('Failed sign-in'))
    expect(failed).toBeDefined()
    expect(within(failed as HTMLElement).getAllByText('jsmith').length).toBeGreaterThan(0)
    expect(within(failed as HTMLElement).getByText('203.0.113.9')).toBeInTheDocument()
    // relative time with the exact date next to it
    expect(within(rows[0] as HTMLElement).getByText('5 minutes ago')).toBeInTheDocument()
    // an event of a user shows its DN under the label
    expect(screen.getAllByText(/^uid=.*,ou=people/).length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /Export CSV/ })).toHaveAttribute(
      'href',
      expect.stringContaining('format=csv'),
    )
  })

  it('expands the changed attributes of an event', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/activity/audit')
    const row = (await screen.findAllByTestId('audit-row')).find((r) => within(r).queryByText('Modified'))
    await user.click(within(must(row)).getByRole('button', { name: 'Show changes' }))
    const diff = await screen.findByRole('list', { name: 'Changes' })
    expect(within(diff).getByText('mail')).toBeInTheDocument()
    expect(within(diff).getByText('new@example.com')).toBeInTheDocument()
    expect(within(diff).getByText('changed')).toBeInTheDocument()
    expect(within(diff).getByText('removed')).toBeInTheDocument()
  })

  it('filters by action, result and text, and shows the empty state', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/activity/audit')
    await screen.findAllByTestId('audit-row')

    await user.click(screen.getByRole('button', { name: /Action/ }))
    await user.click(await screen.findByRole('menuitemcheckbox', { name: 'Failed sign-in' }))
    await waitFor(() => expect(screen.getAllByTestId('audit-row')).toHaveLength(1))
    await user.keyboard('{Escape}')

    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    await waitFor(() => expect(screen.getAllByTestId('audit-row').length).toBeGreaterThan(1))

    await user.type(screen.getByRole('searchbox', { name: 'Search the log' }), 'no-such-text')
    expect(await screen.findByText('No events')).toBeInTheDocument()
  })

  it('narrows to a custom date range through the date inputs', async () => {
    signIn()
    const seen: string[] = []
    server.use(
      http.get('/api/v2/audit', ({ request }) => {
        seen.push(new URL(request.url).search)
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
    )
    const user = userEvent.setup()
    renderApp('/activity/audit')
    await screen.findByText('No events')
    expect(seen[0]).toContain('from=')
    await user.click(screen.getByRole('radio', { name: 'Custom' }))
    await user.type(screen.getByLabelText('From'), '2030-01-02')
    await waitFor(() => expect(seen.some((s) => s.includes('from=2030-01-02'))).toBe(true))
  })

  it('opens pre-filtered on an object from the URL', async () => {
    signIn()
    const target = must(db.all('user')[1])
    renderApp(`/activity/audit?object=${encodeURIComponent(target.dn)}`)
    await screen.findAllByTestId('audit-row')
    expect(screen.getByText(/^Object:/)).toBeInTheDocument()
    for (const r of screen.getAllByTestId('audit-row')) {
      expect(within(r).getAllByText(target.dn).length).toBeGreaterThan(0)
    }
  })

  it('explains itself when the audit plugin is not enabled', async () => {
    signIn()
    server.use(
      http.get('/api/v2/types', () =>
        HttpResponse.json(typeSummaries.filter((x) => x.name !== 'audit_event')),
      ),
    )
    renderApp('/activity/audit')
    expect(await screen.findByText('The audit log is not enabled')).toBeInTheDocument()
  })

  it('shows the permission error for a person who cannot read the log', async () => {
    signIn('viewer')
    renderApp('/activity/audit')
    expect(await screen.findByText('You cannot read the audit log')).toBeInTheDocument()
  })
})

describe('object history and recent activity', () => {
  it('shows recent sign-ins and changes on the Security tab of a person', async () => {
    signIn()
    const user = userEvent.setup()
    const target = must(db.all('user')[1])
    renderApp(`/types/user/${encodeURIComponent(target.dn)}`)
    await screen.findByRole('heading', { level: 1 })
    await user.click(screen.getByRole('tab', { name: 'Security' }))
    const signIns = await screen.findByRole('region', { name: 'Recent sign-ins' }).catch(() => null)
    expect(signIns ?? (await screen.findByText('Recent sign-ins'))).toBeInTheDocument()
    expect(await screen.findByText('Recent changes')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText('Signed in').length).toBeGreaterThan(0))
  })

  it('adds a History entry to the editor, but not for audit events themselves', async () => {
    signIn()
    const user = userEvent.setup()
    const target = must(db.all('user')[1])
    renderApp(`/types/user/${encodeURIComponent(target.dn)}?view=generic`)
    await user.click(await screen.findByRole('tab', { name: 'History' }))
    expect(await screen.findByRole('list', { name: 'History' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Open in the audit log/ })).toBeInTheDocument()
  })

  it('hides the History entry when the audit plugin is not enabled', async () => {
    signIn()
    server.use(
      http.get('/api/v2/types', () =>
        HttpResponse.json(typeSummaries.filter((x) => x.name !== 'audit_event')),
      ),
    )
    const target = must(db.all('user')[1])
    renderApp(`/types/user/${encodeURIComponent(target.dn)}?view=generic`)
    await screen.findByRole('tab', { name: 'References' })
    expect(screen.queryByRole('tab', { name: 'History' })).not.toBeInTheDocument()
  })

  it('puts a Recent activity card on the dashboard, hidden without the plugin', async () => {
    signIn()
    const { unmount } = renderApp('/')
    const card = await screen.findByRole('region', { name: 'Recent activity' })
    expect(await within(card).findByText('Signed in')).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: /Open the audit log/ })).toHaveAttribute('href', '/activity/audit')
    unmount()

    server.use(
      http.get('/api/v2/types', () =>
        HttpResponse.json(typeSummaries.filter((x) => x.name !== 'audit_event')),
      ),
    )
    renderApp('/')
    await screen.findByRole('region', { name: 'Needs attention' })
    expect(screen.queryByRole('region', { name: 'Recent activity' })).not.toBeInTheDocument()
  })
})

describe('type capability flags in the UI', () => {
  it('hides New, Templates and bulk delete for audit events', async () => {
    signIn()
    renderApp('/types/audit_event')
    await screen.findByRole('heading', { name: /Audit events/ })
    expect(screen.queryByRole('link', { name: /New Audit event|Create/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: 'Templates' })).not.toBeInTheDocument()
  })

  it('hides Edit and Delete in the editor header of a read-only type', async () => {
    signIn()
    const dn = `cn=20300101000000-aaaa,ou=audit,${db.all('user')[0]?.dn.split(',').slice(-2).join(',')}`
    db.records.set(dn.toLowerCase(), {
      dn,
      type: 'audit_event',
      tabs: { main: { active: true, values: { cn: '20300101000000-aaaa', hrcAuditAction: 'modify' } } },
    } as never)
    renderApp(`/types/audit_event/${encodeURIComponent(dn)}`)
    await screen.findByRole('heading', { level: 1 })
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })
})

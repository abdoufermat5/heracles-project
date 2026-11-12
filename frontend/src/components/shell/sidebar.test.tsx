import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { NavGroup, NavLevel, TypeSummary } from '@/api/types'
import { server } from '@/mocks/server'
import { renderApp, signIn } from '@/test/utils'

function ty(
  name: string,
  label_plural: string,
  nav: NavLevel,
  nav_group: NavGroup,
  count_key: string | null = null,
): TypeSummary {
  return {
    name,
    label: label_plural,
    label_plural,
    icon: 'file',
    category: 'directory',
    can_create: true,
    nav,
    nav_group,
    count_key,
  }
}

/** A directory with plugins: every kind of type shows up. */
const realistic: TypeSummary[] = [
  ty('user', 'Users', 'primary', 'people', 'user'),
  ty('group', 'Groups', 'primary', 'people', 'group'),
  ty('role', 'Roles', 'primary', 'people', 'role'),
  ty('posix_group', 'POSIX groups', 'secondary', 'people'),
  ty('invitation', 'Invitations', 'secondary', 'people'),
  ty('department', 'Departments', 'primary', 'organization', 'department'),
  ty('department_o', 'Organizations', 'hidden', 'organization'),
  ty('department_l', 'Localities', 'hidden', 'organization'),
  ty('sudo', 'Sudo roles', 'primary', 'access'),
  ty('acl_role', 'Access roles', 'secondary', 'access'),
  ty('dsa', 'Service accounts', 'secondary', 'access'),
  ty('dns_zone', 'DNS zones', 'primary', 'infrastructure'),
  ty('dns_view', 'DNS views', 'secondary', 'infrastructure'),
  ty('server', 'Servers', 'primary', 'infrastructure'),
  ty('workstation', 'Workstations', 'secondary', 'infrastructure'),
  ty('printer', 'Printers', 'secondary', 'infrastructure'),
  ty('mail_alias_redirection', 'Mail redirections', 'secondary', 'mail'),
  ty('archive_task', 'Archive tasks', 'hidden', 'activity'),
  ty('lifecycle_task', 'Lifecycle tasks', 'hidden', 'activity'),
  ty('archived_object', 'Archived objects', 'hidden', 'activity'),
  ty('audit_event', 'Audit events', 'hidden', 'activity'),
  ty('phone_macro', 'Phone macros', 'secondary', 'settings'),
]

function useRealisticTypes(extra: TypeSummary[] = []) {
  server.use(http.get('/api/v2/types', () => HttpResponse.json([...realistic, ...extra])))
}

async function nav() {
  const el = await screen.findByRole('navigation', { name: 'Main navigation' })
  await within(el).findByRole('link', { name: /^Users/ })
  return el
}

describe('sidebar', () => {
  it('keeps the primary navigation to 15 links or fewer', async () => {
    signIn()
    useRealisticTypes()
    renderApp('/')
    const el = await nav()
    await waitFor(() => expect(within(el).getByRole('link', { name: 'Tasks' })).toBeInTheDocument())
    expect(within(el).getAllByRole('link').length).toBeLessThanOrEqual(15)
    expect(within(el).getByRole('link', { name: 'Audit log' })).toHaveAttribute(
      'href',
      '/activity/audit',
    )
  })

  it('never lists hidden or secondary types, but offers them in the command palette', async () => {
    signIn()
    useRealisticTypes()
    const user = userEvent.setup()
    renderApp('/')
    const el = await nav()
    expect(within(el).queryByRole('link', { name: /Archive tasks/ })).not.toBeInTheDocument()
    expect(within(el).queryByRole('link', { name: /Organizations/ })).not.toBeInTheDocument()
    expect(within(el).queryByRole('link', { name: /Printers/ })).not.toBeInTheDocument()

    await user.keyboard('{Control>}k{/Control}')
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Archive tasks')).toBeInTheDocument()
    expect(within(dialog).getByText('Organizations')).toBeInTheDocument()
    expect(within(dialog).getByText('Audit events')).toBeInTheDocument()
    expect(within(dialog).getByText('Printers')).toBeInTheDocument()
  })

  it('puts secondary types behind a per-group More disclosure', async () => {
    signIn()
    useRealisticTypes()
    const user = userEvent.setup()
    renderApp('/')
    const el = await nav()
    const infra = within(el).getByTestId('nav-group-infrastructure')
    expect(within(infra).queryByRole('link', { name: /Printers/ })).not.toBeInTheDocument()
    const more = within(infra).getByRole('button', { name: /More/ })
    expect(more).toHaveAttribute('aria-expanded', 'false')
    await user.click(more)
    expect(within(infra).getByRole('link', { name: /Printers/ })).toBeInTheDocument()
    expect(within(infra).getByRole('link', { name: /Workstations/ })).toBeInTheDocument()
  })

  it('shows no counters next to the links', async () => {
    signIn()
    useRealisticTypes()
    renderApp('/')
    const el = await nav()
    expect(within(el).getByRole('link', { name: /^Users/ })).toHaveTextContent(/^Users$/)
    expect(el).not.toHaveTextContent(/\d/)
  })

  it('remembers collapsed groups', async () => {
    signIn()
    useRealisticTypes()
    const user = userEvent.setup()
    const first = renderApp('/')
    let el = await nav()
    await user.click(within(el).getByRole('button', { name: /Show or hide Infrastructure/ }))
    expect(within(el).queryByRole('link', { name: /Servers/ })).not.toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('heracles.nav.collapsedGroups') ?? '[]')).toEqual([
      'infrastructure',
    ])
    first.unmount()

    renderApp('/')
    el = await screen.findByRole('navigation', { name: 'Main navigation' })
    await within(el).findByRole('link', { name: /^Users/ })
    expect(within(el).queryByRole('link', { name: /Servers/ })).not.toBeInTheDocument()
    expect(
      within(el).getByRole('button', { name: /Show or hide Infrastructure/ }),
    ).toHaveAttribute('aria-expanded', 'false')
  })

  it('pins favourites to the top and remembers them', async () => {
    signIn()
    useRealisticTypes()
    const user = userEvent.setup()
    renderApp('/')
    const el = await nav()
    await user.click(within(el).getByRole('button', { name: 'Pin Servers to the top' }))
    const fav = within(el).getByTestId('nav-favorites')
    expect(within(fav).getByRole('link', { name: /Servers/ })).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('heracles.nav.favorites') ?? '[]')).toEqual(['server'])
    await user.click(within(fav).getByRole('button', { name: 'Unpin Servers' }))
    expect(within(el).queryByTestId('nav-favorites')).not.toBeInTheDocument()
  })

  it('filters across every listed type, secondary ones included', async () => {
    signIn()
    useRealisticTypes([
      ty('netgroup', 'Netgroups', 'primary', 'infrastructure'),
      ty('dns_acl', 'DNS access lists', 'primary', 'infrastructure'),
      ty('component', 'Network devices', 'primary', 'infrastructure'),
      ty('phone', 'Phones', 'primary', 'infrastructure'),
    ])
    const user = userEvent.setup()
    renderApp('/')
    const el = await nav()
    const box = await within(el).findByRole('searchbox', { name: 'Filter navigation' })
    await user.type(box, 'print')
    expect(within(el).getByRole('link', { name: /Printers/ })).toBeInTheDocument()
    expect(within(el).queryByRole('link', { name: /^Users/ })).not.toBeInTheDocument()
  })
})

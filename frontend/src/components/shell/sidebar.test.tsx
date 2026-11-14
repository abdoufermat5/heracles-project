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
  it('keeps the directory navigation to 15 links or fewer, admin tools apart', async () => {
    signIn()
    useRealisticTypes()
    renderApp('/')
    const el = await nav()
    await within(el).findByTestId('nav-admin')
    const directory = within(el).getByTestId('nav-directory')
    expect(within(directory).getAllByRole('link').length).toBeLessThanOrEqual(15)
    // Admin tools are not interleaved with object types.
    expect(within(directory).queryByRole('link', { name: 'Tasks' })).not.toBeInTheDocument()
    expect(within(directory).queryByRole('link', { name: 'Audit log' })).not.toBeInTheDocument()
  })

  it('never lists hidden types, but offers them in the command palette', async () => {
    signIn()
    useRealisticTypes()
    const user = userEvent.setup()
    renderApp('/')
    const el = await nav()
    expect(within(el).queryByRole('link', { name: /Archive tasks/ })).not.toBeInTheDocument()
    expect(within(el).queryByRole('link', { name: /Organizations/ })).not.toBeInTheDocument()
    expect(within(el).queryByRole('link', { name: /Access roles/ })).not.toBeInTheDocument()

    await user.keyboard('{Control>}k{/Control}')
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Archive tasks')).toBeInTheDocument()
    expect(within(dialog).getByText('Organizations')).toBeInTheDocument()
    expect(within(dialog).getByText('Audit events')).toBeInTheDocument()
    expect(within(dialog).getByText('Printers')).toBeInTheDocument()
  })

  it('has plain, non-collapsible group headings and no per-group More', async () => {
    signIn()
    useRealisticTypes()
    renderApp('/')
    const el = await nav()
    const people = within(el).getByTestId('nav-group-people')
    expect(within(people).getByRole('heading', { name: 'People' })).toBeInTheDocument()
    expect(within(people).queryByRole('button', { name: 'People' })).not.toBeInTheDocument()
    expect(within(el).queryByRole('button', { name: /^More$/ })).not.toBeInTheDocument()
  })

  it('shows every type of a small group and folds a large one behind “+N more”', async () => {
    signIn()
    useRealisticTypes()
    const user = userEvent.setup()
    renderApp('/')
    const el = await nav()
    // Access has two types: all listed, nothing to expand.
    const access = within(el).getByTestId('nav-group-access')
    expect(within(access).getByRole('link', { name: /Service accounts/ })).toBeInTheDocument()
    expect(within(access).queryByRole('button', { expanded: false })).not.toBeInTheDocument()

    // Infrastructure has five: primary + one expander counting the two hidden ones.
    const infra = within(el).getByTestId('nav-group-infrastructure')
    expect(within(infra).queryByRole('link', { name: /Printers/ })).not.toBeInTheDocument()
    const more = within(infra).getByRole('button', { name: '+3 more' })
    expect(more).toHaveAttribute('aria-expanded', 'false')
    await user.click(more)
    expect(within(infra).getByRole('link', { name: /Printers/ })).toBeInTheDocument()
    expect(within(infra).getByRole('link', { name: /Workstations/ })).toBeInTheDocument()
    await user.click(within(infra).getByRole('button', { name: 'Show fewer' }))
    expect(within(infra).queryByRole('link', { name: /Printers/ })).not.toBeInTheDocument()
  })

  it('expands a group by itself when the open page is one of its folded types', async () => {
    signIn()
    useRealisticTypes()
    renderApp('/types/printer')
    const el = await screen.findByRole('navigation', { name: 'Main navigation' })
    const infra = await within(el).findByTestId('nav-group-infrastructure')
    expect(await within(infra).findByRole('link', { name: /Printers/ })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })

  it('promotes secondary types of a group that has no primary one', async () => {
    signIn()
    useRealisticTypes()
    renderApp('/')
    const el = await nav()
    const mail = within(el).getByTestId('nav-group-mail')
    expect(within(mail).getByRole('link', { name: /Mail redirections/ })).toBeInTheDocument()
    expect(within(mail).queryByRole('button', { expanded: false })).not.toBeInTheDocument()
  })

  it('never renders a group without a link', async () => {
    signIn()
    useRealisticTypes()
    renderApp('/')
    const el = await nav()
    // `activity` only declares hidden types here.
    expect(within(el).queryByTestId('nav-group-activity')).not.toBeInTheDocument()
    for (const group of within(el).getAllByTestId(/^nav-group-/)) {
      expect(within(group).getAllByRole('link').length).toBeGreaterThan(0)
    }
  })

  it('shows no counters next to the links', async () => {
    signIn()
    useRealisticTypes()
    renderApp('/')
    const el = await nav()
    expect(within(el).getByRole('link', { name: /^Users/ })).toHaveTextContent(/^Users$/)
    for (const link of within(el).getAllByRole('link')) expect(link).not.toHaveTextContent(/\d/)
  })

  it('groups the admin tools in one collapsible block', async () => {
    signIn()
    useRealisticTypes()
    const user = userEvent.setup()
    renderApp('/')
    const el = await nav()
    const admin = await within(el).findByTestId('nav-admin')
    const toggle = within(admin).getByRole('button', { name: 'Administration' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(within(admin).queryByRole('link')).not.toBeInTheDocument()

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(within(admin).getByRole('link', { name: 'Tasks' })).toBeInTheDocument()
    expect(within(admin).getByRole('link', { name: 'Configuration' })).toBeInTheDocument()
    expect(within(admin).getByRole('link', { name: 'Audit log' })).toHaveAttribute(
      'href',
      '/activity/audit',
    )
    expect(localStorage.getItem('heracles.nav.adminOpen')).toBe('1')
  })

  it('opens the admin block on an admin page and keeps its link visible', async () => {
    signIn()
    useRealisticTypes()
    const user = userEvent.setup()
    renderApp('/admin/config')
    const el = await screen.findByRole('navigation', { name: 'Main navigation' })
    const admin = await within(el).findByTestId('nav-admin')
    const link = await within(admin).findByRole('link', { name: 'Configuration' })
    expect(link).toHaveAttribute('aria-current', 'page')
    const toggle = within(admin).getByRole('button', { name: 'Administration' })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await user.click(toggle)
    expect(within(admin).getByRole('link', { name: 'Configuration' })).toBeInTheDocument()
  })

  it('drops the retired per-group collapse state', async () => {
    signIn()
    localStorage.setItem('heracles.nav.collapsedGroups', JSON.stringify(['infrastructure']))
    useRealisticTypes()
    renderApp('/')
    const el = await nav()
    expect(within(el).getByRole('link', { name: /Servers/ })).toBeInTheDocument()
    await waitFor(() => expect(localStorage.getItem('heracles.nav.collapsedGroups')).toBeNull())
  })

  it('offers a retry instead of an empty navigation when the types fail to load', async () => {
    signIn()
    let fail = true
    server.use(
      http.get('/api/v2/types', () =>
        fail
          ? HttpResponse.json({ error: { code: 'boom', message: 'x' } }, { status: 500 })
          : HttpResponse.json(realistic),
      ),
    )
    const user = userEvent.setup()
    renderApp('/')
    const el = await screen.findByRole('navigation', { name: 'Main navigation' })
    const alert = await within(el).findByRole('alert', {}, { timeout: 8000 })
    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await within(el).findByRole('link', { name: /^Users/ })).toBeInTheDocument()
  }, 15000)

  it('pins favourites to the top and remembers them', async () => {
    signIn()
    useRealisticTypes()
    const user = userEvent.setup()
    renderApp('/')
    const el = await nav()
    await user.click(within(el).getByRole('button', { name: 'Pin Servers to the top' }))
    const fav = within(el).getByTestId('nav-favorites')
    expect(within(fav).getByRole('heading', { name: 'Pinned' })).toBeInTheDocument()
    expect(within(fav).getByRole('link', { name: /Servers/ })).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('heracles.nav.favorites') ?? '[]')).toEqual(['server'])
    await user.click(within(fav).getByRole('button', { name: 'Unpin Servers' }))
    expect(within(el).queryByTestId('nav-favorites')).not.toBeInTheDocument()
  })

  it('filters across every listed type, folded and admin ones included', async () => {
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
    await user.clear(box)
    await user.type(box, 'config')
    expect(within(el).getByRole('link', { name: 'Configuration' })).toBeInTheDocument()
  })
})

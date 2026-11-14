import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import i18n from '@/i18n'
import { db } from '@/mocks/db'
import { server } from '@/mocks/server'
import { renderApp, signIn } from '@/test/utils'
import { guessMapping } from './mapping'

const LDIF = [
  'dn: ou=Imported,dc=example,dc=com',
  'objectClass: organizationalUnit',
  'ou: Imported',
  '',
  'dn: uid=nobody,ou=Paris,dc=example,dc=com',
  '',
].join('\n')

async function open(path = '/io') {
  signIn()
  renderApp(path)
  return await screen.findByRole('heading', { name: 'Import / export' })
}

describe('import / export page', () => {
  it('is listed in the sidebar and shows the three tabs', async () => {
    signIn()
    renderApp('/')
    const link = await screen.findByRole('link', { name: 'Import / export' })
    await userEvent.click(link)
    expect(await screen.findByRole('tab', { name: 'Export LDIF' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Import LDIF' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Import CSV' })).toBeInTheDocument()
  })

  it('hides the tabs the user has no right for, and the page when none is left', async () => {
    server.use(
      http.get('/api/v2/ldapmanager/access', () =>
        HttpResponse.json({ ldif_export: true, ldif_import: false, csv_import: false }),
      ),
    )
    await open()
    expect(await screen.findByRole('tab', { name: 'Export LDIF' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Import LDIF' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Import CSV' })).not.toBeInTheDocument()
  })

  it('shows an empty state without any right', async () => {
    server.use(
      http.get('/api/v2/ldapmanager/access', () =>
        HttpResponse.json({ ldif_export: false, ldif_import: false, csv_import: false }),
      ),
    )
    await open()
    expect(await screen.findByText('No import or export rights')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Import / export' })).not.toBeInTheDocument()
  })

  it('builds the export download link from the form', async () => {
    await open()
    const link = await screen.findByRole('link', { name: 'Download LDIF' })
    const initial = new URL(link.getAttribute('href') ?? '', 'http://localhost')
    expect(initial.pathname).toBe('/api/v2/ldif/export')
    expect(initial.searchParams.get('scope')).toBe('sub')
    expect(initial.searchParams.get('wrap')).toBe('76')

    await userEvent.type(screen.getByLabelText('Base DN'), 'ou=Paris,dc=example,dc=com')
    await userEvent.selectOptions(screen.getByLabelText('Scope'), 'one')
    const wrap = screen.getByLabelText(/Wrap lines after/)
    await userEvent.clear(wrap)
    await userEvent.type(wrap, '0')
    const url = new URL(
      screen.getByRole('link', { name: 'Download LDIF' }).getAttribute('href') ?? '',
      'http://localhost',
    )
    expect(url.searchParams.get('base')).toBe('ou=Paris,dc=example,dc=com')
    expect(url.searchParams.get('scope')).toBe('one')
    expect(url.searchParams.get('wrap')).toBe('0')
  })
})

describe('LDIF import', () => {
  async function paste(text: string) {
    await userEvent.click(await screen.findByRole('tab', { name: 'Import LDIF' }))
    await userEvent.click(await screen.findByLabelText('Or paste LDIF text'))
    await userEvent.paste(text)
  }

  it('warns that the import is raw and previews before applying', async () => {
    await open()
    await paste(LDIF)
    expect(screen.getByText(/bypasses the validation/)).toBeInTheDocument()
    const apply = screen.getByRole('button', { name: 'Apply import' })
    expect(apply).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Preview (dry run)' }))
    expect(await screen.findByText('Preview: nothing has been written yet')).toBeInTheDocument()
    const rows = screen.getAllByRole('row')
    expect(within(rows[1] as HTMLElement).getByText('Added')).toBeInTheDocument()
    expect(within(rows[2] as HTMLElement).getByText('Entry without objectClass')).toBeInTheDocument()
    expect(screen.getByLabelText('Summary')).toHaveTextContent('Errors: 1')
    expect(screen.getByRole('button', { name: 'Apply import' })).toBeEnabled()
  })

  it('applies the import and reports the result', async () => {
    const calls: boolean[] = []
    server.events.on('request:start', async ({ request }) => {
      if (new URL(request.url).pathname.endsWith('/ldif/import')) {
        const body = (await request.clone().json()) as { dry_run: boolean }
        calls.push(body.dry_run)
      }
    })
    await open()
    await paste(LDIF)
    await userEvent.click(screen.getByRole('button', { name: 'Preview (dry run)' }))
    await screen.findByText('Preview: nothing has been written yet')
    await userEvent.click(screen.getByRole('button', { name: 'Apply import' }))
    expect(await screen.findByText('Import result')).toBeInTheDocument()
    await waitFor(() => expect(calls).toEqual([true, false]))
  })

  it('changing the text invalidates the preview; remove-missing needs overwrite', async () => {
    await open()
    await paste(LDIF)
    const remove = screen.getByLabelText(/Remove attributes that are not in the LDIF/)
    expect(remove).toBeDisabled()
    await userEvent.click(screen.getByLabelText('Overwrite existing entries'))
    expect(remove).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Preview (dry run)' }))
    await screen.findByText('Preview: nothing has been written yet')
    await userEvent.click(screen.getByLabelText('Or paste LDIF text'))
    await userEvent.paste('\n')
    expect(screen.getByRole('button', { name: 'Apply import' })).toBeDisabled()
  })

  it('shows the server error for an invalid document', async () => {
    server.use(
      http.post('/api/v2/ldif/import', () =>
        HttpResponse.json(
          { error: { code: 'validation', message: 'Invalid LDIF: line 1' } },
          { status: 422 },
        ),
      ),
    )
    await open()
    await paste('garbage')
    await userEvent.click(screen.getByRole('button', { name: 'Preview (dry run)' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid LDIF: line 1')
  })
})

describe('CSV import', () => {
  const CSV = 'uid,givenName,sn,mail\nimp1,Ada,Lovelace,ada@example.com\nimp2,,Hopper,grace@example.com\n'

  async function load(text = CSV) {
    await userEvent.click(await screen.findByRole('tab', { name: 'Import CSV' }))
    await userEvent.click(await screen.findByLabelText('Or paste CSV text'))
    await userEvent.paste(text)
    await userEvent.click(screen.getByRole('button', { name: 'Load and preview' }))
  }

  it('previews, maps the columns by header and reports per-line results', async () => {
    await open()
    await load()
    expect(await screen.findByText('Preview: first 2 lines of 2')).toBeInTheDocument()
    // columns are pre-mapped from their headers
    expect(screen.getByLabelText('uid')).toHaveValue('main.uid')
    expect(screen.getByLabelText('givenName')).toHaveValue('main.givenName')
    expect(screen.getByLabelText('sn')).toHaveValue('main.sn')
    expect(screen.getByLabelText('mail')).toHaveValue('main.mail')

    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByText('1 entry successfully imported')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(/Import failed for line 3: main\.givenName/)
    expect(db.all('user').some((u) => u.tabs.main?.values.uid === 'imp1')).toBe(true)
    expect(db.all('user').some((u) => u.tabs.main?.values.uid === 'imp2')).toBe(false)
  })

  it('lets the user remap columns and set fixed values', async () => {
    const bodies: { mapping: { column: number; field: string }[]; fixed: Record<string, string> }[] = []
    server.use(
      http.post('/api/v2/csv/:type/import', async ({ request }) => {
        bodies.push((await request.json()) as (typeof bodies)[number])
        return HttpResponse.json({ imported: 2, failed: 0, results: [] })
      }),
    )
    await open()
    await load('login;name\nimp1;Lovelace\nimp2;Hopper\n')
    await screen.findByText(/Preview/)
    // the separator is wrong: a single column is found
    await userEvent.selectOptions(screen.getByLabelText('Separator'), ';')
    await userEvent.click(screen.getByRole('button', { name: 'Load and preview' }))
    await screen.findByLabelText('login')
    await userEvent.selectOptions(screen.getByLabelText('login'), 'main.uid')
    await userEvent.selectOptions(screen.getByLabelText('name'), 'main.sn')
    await userEvent.click(screen.getByRole('button', { name: 'Add a fixed value' }))
    await userEvent.selectOptions(screen.getByLabelText('Attribute'), 'main.givenName')
    await userEvent.type(screen.getByLabelText('Value'), 'Imported')
    await userEvent.click(screen.getByRole('button', { name: 'Import' }))
    expect(await screen.findByText('2 entries successfully imported')).toBeInTheDocument()
    expect(bodies[0]?.mapping).toEqual([
      { column: 0, field: 'main.uid' },
      { column: 1, field: 'main.sn' },
    ])
    expect(bodies[0]?.fixed).toEqual({ 'main.givenName': 'Imported' })
  })

  it('offers templates when the objects module provides them and restricts the fields', async () => {
    const queries: (string | null)[] = []
    server.use(
      http.get('/api/v2/types/user/templates', () =>
        HttpResponse.json([{ dn: 'cn=tpl,ou=templates,dc=example,dc=com', name: 'Staff', type_name: 'user' }]),
      ),
      http.get('/api/v2/csv/user/fields', ({ request }) => {
        const template = new URL(request.url).searchParams.get('template')
        queries.push(template)
        const field = {
          key: 'main.sn',
          tab: 'main',
          tab_label: 'Identity',
          attribute: 'sn',
          label: 'Last name',
          kind: 'string',
          required: true,
          multivalued: false,
        }
        return HttpResponse.json(template ? [field] : [field, { ...field, key: 'main.uid', attribute: 'uid' }])
      }),
    )
    await open()
    await userEvent.click(await screen.findByRole('tab', { name: 'Import CSV' }))
    const select = await screen.findByLabelText('Template')
    await userEvent.selectOptions(select, 'cn=tpl,ou=templates,dc=example,dc=com')
    await waitFor(() => expect(queries).toContain('cn=tpl,ou=templates,dc=example,dc=com'))
  })

  it('shows a server error when the CSV cannot be read', async () => {
    server.use(
      http.post('/api/v2/csv/parse', () =>
        HttpResponse.json({ error: { code: 'validation', message: 'The CSV is empty' } }, { status: 422 }),
      ),
    )
    await open()
    await load('x')
    expect(await screen.findByRole('alert')).toHaveTextContent('The CSV is empty')
  })

  it('renders in French', async () => {
    await i18n.changeLanguage('fr')
    try {
      await open()
      expect(await screen.findByRole('tab', { name: 'Export LDIF' })).toBeInTheDocument()
      await userEvent.click(screen.getByRole('tab', { name: 'Import LDIF' }))
      expect(await screen.findByText(/contourne la validation/)).toBeInTheDocument()
    } finally {
      await i18n.changeLanguage('en')
    }
  })
})

describe('guessMapping', () => {
  const field = (attribute: string, label: string) => ({
    key: `main.${attribute}`,
    tab: 'main',
    tab_label: 'Identity',
    attribute,
    label,
    kind: 'string',
    required: false,
    multivalued: false,
  })

  it('matches attribute names and labels case-insensitively, once per field', () => {
    const fields = [field('uid', 'Login'), field('sn', 'Last name')]
    expect(guessMapping(['UID', 'last name', 'uid', 'other'], fields)).toEqual({
      0: 'main.uid',
      1: 'main.sn',
    })
  })
})

describe('import / export availability', () => {
  const caps = (io: boolean) => ({
    is_admin: true,
    console: true,
    acl: true,
    config: true,
    config_write: true,
    hooks: true,
    health: true,
    plugins: true,
    tasks: true,
    io,
  })

  it('asks for no rights and says the module is off when the capability says the plugin is off', async () => {
    server.use(
      http.get('/api/v2/admin/capabilities', () => HttpResponse.json(caps(false))),
    )
    signIn()
    const probed: string[] = []
    const listener = ({ request }: { request: Request }) => {
      const path = new URL(request.url).pathname
      if (path === '/api/v2/ldapmanager/access') probed.push(path)
    }
    server.events.on('request:start', listener)

    renderApp('/io')
    expect(await screen.findByText('The import / export module is off')).toBeInTheDocument()
    expect(probed).toEqual([])
    expect(screen.queryByRole('link', { name: 'Import / export' })).not.toBeInTheDocument()

    server.events.removeListener('request:start', listener)
  })

  it('keeps the navigation and the dashboard checklist entry when the plugin is available', async () => {
    server.use(
      http.get('/api/v2/admin/capabilities', () => HttpResponse.json(caps(true))),
    )
    signIn()
    const first = renderApp('/')
    expect(await screen.findByRole('link', { name: 'Import / export' })).toBeInTheDocument()
    expect(await screen.findByText('Import your users')).toBeInTheDocument()
    first.unmount()

    server.use(
      http.get('/api/v2/admin/capabilities', () => HttpResponse.json(caps(false))),
    )
    renderApp('/')
    await screen.findByRole('region', { name: 'Needs attention' })
    expect(screen.queryByText('Import your users')).not.toBeInTheDocument()
    expect(screen.queryByText('Import people')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Import / export' })).not.toBeInTheDocument()
  })
})

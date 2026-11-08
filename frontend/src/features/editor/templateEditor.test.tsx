import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { objectsApi } from '@/features/editor/api'
import { db } from '@/mocks/db'
import { seedDemoTemplates } from '@/mocks/objectsHandlers'
import { server } from '@/mocks/server'
import { renderApp, signIn } from '@/test/utils'

const TEMPLATE_DN = 'cn=staff,ou=templates,ou=people,dc=example,dc=com'

describe('templates view and editor', () => {
  it('lists, creates, edits and deletes templates', async () => {
    seedDemoTemplates()
    signIn()
    renderApp('/types/user')
    await userEvent.click(await screen.findByRole('radio', { name: 'Templates' }))
    expect(await screen.findByRole('link', { name: 'staff' })).toBeInTheDocument()

    // create
    await userEvent.click(screen.getByRole('link', { name: /New template/ }))
    await userEvent.type(await screen.findByLabelText(/^Template name/), 'interns')
    await userEvent.type(screen.getByLabelText(/^Login/), '%givenName%.%sn%')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect(await screen.findByRole('link', { name: 'interns' })).toBeInTheDocument()
    const stored = [...db.templates.values()].find((t) => t.name === 'interns')
    expect(stored?.tabs.main?.values.uid).toBe('%givenName%.%sn%')

    // edit
    await userEvent.click(screen.getByRole('link', { name: 'Edit interns' }))
    const login = await screen.findByLabelText(/^Login/)
    expect(login).toHaveValue('%givenName%.%sn%')
    await userEvent.clear(login)
    await userEvent.type(login, 'intern-%sn%')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByRole('link', { name: 'interns' })
    expect(db.templates.get(stored?.dn.toLowerCase() ?? '')?.tabs.main?.values.uid).toBe('intern-%sn%')

    // delete
    await userEvent.click(screen.getByRole('button', { name: 'Delete interns' }))
    const dialog = await screen.findByRole('alertdialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(screen.queryByRole('link', { name: 'interns' })).not.toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'staff' })).toBeInTheDocument()
  })

  it('shows the empty state and the mask syntax help', async () => {
    signIn()
    renderApp('/types/group?view=templates')
    expect(await screen.findByText('No templates yet')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('link', { name: /New template/ })[0]!)
    await userEvent.click(await screen.findByRole('button', { name: 'Mask syntax' }))
    expect(await screen.findByText(/%attr% inserts the value of an attribute/)).toBeInTheDocument()
  })

  it('maps server validation errors onto the template fields', async () => {
    seedDemoTemplates()
    signIn()
    server.use(
      http.patch('/api/v2/types/:type/templates/:dn', () =>
        HttpResponse.json(
          { error: { code: 'validation', message: 'Invalid', fields: { 'main.uid': 'Circular reference: uid -> uid' } } },
          { status: 422 },
        ),
      ),
    )
    renderApp(`/types/user/templates/${encodeURIComponent(TEMPLATE_DN)}`)
    const login = await screen.findByLabelText(/^Login/)
    await userEvent.clear(login)
    await userEvent.type(login, '%uid%')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Circular reference: uid -> uid')).toBeInTheDocument()
    expect(login).toHaveAttribute('aria-invalid', 'true')
  })

  it('exposes the template API calls', async () => {
    seedDemoTemplates()
    signIn()
    renderApp('/')
    await screen.findByRole('heading', { level: 1 })
    const fields = await objectsApi.templateFields('user', TEMPLATE_DN)
    expect(fields.fields).toEqual({ main: ['givenName', 'sn'] })
  })
})

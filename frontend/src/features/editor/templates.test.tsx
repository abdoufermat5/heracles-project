import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { db } from '@/mocks/db'
import { seedDemoTemplates } from '@/mocks/objectsHandlers'
import { renderApp, signIn } from '@/test/utils'

const TEMPLATE_DN = 'cn=staff,ou=templates,ou=people,dc=example,dc=com'

describe('create from a template', () => {
  it('lists the templates, asks only for the open fields and previews the result', async () => {
    seedDemoTemplates()
    signIn()
    const create = vi.spyOn(
      await import('@/api/endpoints').then((m) => m.api),
      'createObject',
    )
    renderApp('/types/user/new')

    await userEvent.click(await screen.findByRole('combobox', { name: /Create from a template/ }))
    await userEvent.click(await screen.findByRole('option', { name: 'staff' }))

    // Only what the template leaves open: first and last name (and the department).
    const givenName = await screen.findByLabelText(/^First name/)
    expect(screen.queryByLabelText(/^Login/)).not.toBeInTheDocument()
    await userEvent.type(givenName, 'John')
    await userEvent.type(screen.getByLabelText(/^Last name/), 'Doe')

    const preview = await screen.findByTestId('template-preview')
    await waitFor(() => expect(within(preview).getByText('jdoe')).toBeInTheDocument())
    expect(within(preview).getByText('John Doe')).toBeInTheDocument()
    expect(within(preview).getByText('jdoe@example.com')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Create user/ }))
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    const body = create.mock.calls[0]?.[1]
    expect(body?.template).toBe(TEMPLATE_DN)
    expect(body?.tabs).toEqual({ main: { active: true, values: { givenName: 'John', sn: 'Doe' } } })
    await waitFor(() => expect(db.get('uid=jdoe,ou=people,dc=example,dc=com')).toBeDefined())
  })

  it('requires the template fields before calling the API', async () => {
    seedDemoTemplates()
    signIn()
    const create = vi.spyOn(await import('@/api/endpoints').then((m) => m.api), 'createObject')
    renderApp('/types/user/new')
    await userEvent.click(await screen.findByRole('combobox', { name: /Create from a template/ }))
    await userEvent.click(await screen.findByRole('option', { name: 'staff' }))
    await screen.findByLabelText(/^First name/)
    await userEvent.click(screen.getByRole('button', { name: /Create user/ }))
    expect((await screen.findAllByText('This field is required')).length).toBeGreaterThan(0)
    expect(create).not.toHaveBeenCalled()
  })

  it('can go back to a blank object', async () => {
    seedDemoTemplates()
    signIn()
    renderApp('/types/user/new')
    await userEvent.click(await screen.findByRole('combobox', { name: /Create from a template/ }))
    await userEvent.click(await screen.findByRole('option', { name: 'staff' }))
    await screen.findByLabelText(/^First name/)
    await userEvent.click(screen.getByRole('combobox', { name: /Create from a template/ }))
    await userEvent.click(await screen.findByRole('option', { name: /Blank/ }))
    expect(await screen.findByLabelText(/^Login/)).toBeInTheDocument()
  })

  it('shows no picker when the type has no template', async () => {
    signIn()
    renderApp('/types/user/new')
    await screen.findByLabelText(/^Login/)
    expect(screen.queryByRole('combobox', { name: /Create from a template/ })).not.toBeInTheDocument()
  })
})

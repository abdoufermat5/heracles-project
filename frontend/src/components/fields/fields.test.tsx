import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import type { AttributeDescriptor } from '@/api/types'
import { db } from '@/mocks/db'
import { must, renderWithQuery, signIn } from '@/test/utils'
import { FieldInput } from './FieldInput'
import { passwordStrength } from '@/lib/password'

function Harness({
  descriptor,
  initial = null,
  readOnly,
  onValue,
}: {
  descriptor: AttributeDescriptor
  initial?: unknown
  readOnly?: boolean
  onValue?: (v: unknown) => void
}) {
  const [value, setValue] = useState<unknown>(initial)
  return (
    <>
      <label htmlFor="x">{descriptor.label}</label>
      <FieldInput
        descriptor={descriptor}
        id="x"
        value={value}
        readOnly={readOnly}
        onChange={(v) => {
          setValue(v)
          onValue?.(v)
        }}
      />
    </>
  )
}

const base = (a: Partial<AttributeDescriptor>): AttributeDescriptor => ({
  name: 'a',
  label: 'Field',
  kind: 'string',
  ...a,
})

describe('field components', () => {
  it('string: emits typed text and null when cleared', async () => {
    const onValue = vi.fn()
    renderWithQuery(<Harness descriptor={base({})} onValue={onValue} />)
    const input = screen.getByLabelText('Field')
    await userEvent.type(input, 'ab')
    expect(onValue).toHaveBeenLastCalledWith('ab')
    await userEvent.clear(input)
    expect(onValue).toHaveBeenLastCalledWith(null)
  })

  it('int: emits numbers', async () => {
    const onValue = vi.fn()
    renderWithQuery(<Harness descriptor={base({ kind: 'int' })} onValue={onValue} />)
    await userEvent.type(screen.getByLabelText('Field'), '42')
    expect(onValue).toHaveBeenLastCalledWith(42)
  })

  it('boolean: toggles', async () => {
    const onValue = vi.fn()
    renderWithQuery(<Harness descriptor={base({ kind: 'boolean' })} initial={false} onValue={onValue} />)
    await userEvent.click(screen.getByRole('switch'))
    expect(onValue).toHaveBeenLastCalledWith(true)
  })

  it('select: lists options', async () => {
    const onValue = vi.fn()
    renderWithQuery(
      <Harness
        descriptor={base({
          kind: 'select',
          options: [
            { value: 'fr', label: 'Français' },
            { value: 'en', label: 'English' },
          ],
        })}
        onValue={onValue}
      />,
    )
    await userEvent.selectOptions(screen.getByLabelText('Field'), 'fr')
    expect(onValue).toHaveBeenLastCalledWith('fr')
  })

  it('multiselect: adds and removes values', async () => {
    const onValue = vi.fn()
    renderWithQuery(
      <Harness
        descriptor={base({
          kind: 'multiselect',
          options: [
            { value: 'a', label: 'Alpha' },
            { value: 'b', label: 'Beta' },
          ],
        })}
        initial={[]}
        onValue={onValue}
      />,
    )
    await userEvent.click(screen.getByLabelText('Alpha'))
    await userEvent.click(screen.getByLabelText('Beta'))
    expect(onValue).toHaveBeenLastCalledWith(['a', 'b'])
    await userEvent.click(screen.getByLabelText('Alpha'))
    expect(onValue).toHaveBeenLastCalledWith(['b'])
  })

  it('read-only fields are disabled', () => {
    renderWithQuery(<Harness descriptor={base({})} initial="locked" readOnly />)
    expect(screen.getByLabelText('Field')).toBeDisabled()
  })

  it('password: shows strength meter and flags mismatching confirmation', async () => {
    renderWithQuery(<Harness descriptor={base({ kind: 'password' })} />)
    await userEvent.type(screen.getByLabelText('Field'), 'Abcdef12!xyz')
    expect(screen.getByRole('meter')).toHaveAttribute('aria-valuenow', '4')
    await userEvent.type(screen.getByLabelText('Confirm password'), 'nope')
    expect(screen.getByRole('alert')).toHaveTextContent('Passwords do not match')
  })

  it('passwordStrength scores', () => {
    expect(passwordStrength('')).toBe(0)
    expect(passwordStrength('abc')).toBe(1)
    expect(passwordStrength('Abcdef12!xyz')).toBe(4)
  })

  it('password: generates strong password when generate button is clicked', async () => {
    const onValue = vi.fn()
    renderWithQuery(<Harness descriptor={base({ kind: 'password' })} onValue={onValue} />)
    const genBtn = screen.getByRole('button', { name: /Generate password/i })
    await userEvent.click(genBtn)
    expect(onValue).toHaveBeenCalled()
    expect(screen.getByRole('meter')).toHaveAttribute('aria-valuenow', '4')
  })

  it('list: add, edit, reorder and remove entries', async () => {
    const onValue = vi.fn()
    renderWithQuery(
      <Harness
        descriptor={base({ kind: 'list', item: base({ name: 'ns', label: 'NS' }) })}
        initial={['one', 'two']}
        onValue={onValue}
      />,
    )
    await userEvent.click(must(screen.getAllByRole('button', { name: 'Move down' })[0]))
    expect(onValue).toHaveBeenLastCalledWith(['two', 'one'])
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(onValue).toHaveBeenLastCalledWith(['two', 'one', null])
    await userEvent.click(screen.getByRole('button', { name: 'Remove 1' }))
    expect(onValue).toHaveBeenLastCalledWith(['one', null])
  })

  it('composite: edits sub-fields', async () => {
    const onValue = vi.fn()
    renderWithQuery(
      <Harness
        descriptor={base({
          kind: 'composite',
          fields: [base({ name: 'host', label: 'Host' }), base({ name: 'port', label: 'Port', kind: 'int' })],
        })}
        initial={{ host: null, port: null }}
        onValue={onValue}
      />,
    )
    await userEvent.type(screen.getByLabelText('Host'), 'h')
    expect(onValue).toHaveBeenLastCalledWith({ host: 'h', port: null })
    await userEvent.type(screen.getByLabelText('Port'), '8')
    expect(onValue).toHaveBeenLastCalledWith({ host: 'h', port: 8 })
  })

  it('object_ref: searches the referenced type asynchronously and picks a result', async () => {
    signIn()
    const onValue = vi.fn()
    renderWithQuery(
      <Harness descriptor={base({ kind: 'object_ref', ref_type: 'group', label: 'Parent' })} onValue={onValue} />,
    )
    await userEvent.click(screen.getByRole('combobox'))
    await userEvent.type(screen.getByLabelText('Search…'), 'devel')
    const option = await screen.findByText('developers', {}, { timeout: 4000 })
    await userEvent.click(option)
    await waitFor(() => expect(onValue).toHaveBeenCalled())
    const dn = db.all('group').find((g) => g.dn.includes('developers'))?.dn
    expect(onValue).toHaveBeenLastCalledWith(dn)
  })
})

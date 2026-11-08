import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { db } from '@/mocks/db'
import { renderApp, signIn } from '@/test/utils'

function fakeKeys(opts: { get?: unknown; create?: unknown } = {}): void {
  vi.stubGlobal('PublicKeyCredential', class {})
  Object.defineProperty(navigator, 'credentials', {
    value: { get: opts.get ?? vi.fn(), create: opts.create ?? vi.fn() },
    configurable: true,
  })
}

const attestation = {
  id: 'mock-key',
  rawId: new Uint8Array([1]).buffer,
  type: 'public-key',
  response: {
    attestationObject: new Uint8Array([1]).buffer,
    clientDataJSON: new Uint8Array([2]).buffer,
    getTransports: () => [],
  },
  getClientExtensionResults: () => ({}),
}

afterEach(() => {
  vi.unstubAllGlobals()
  Object.defineProperty(navigator, 'credentials', { value: undefined, configurable: true })
})

describe('security keys panel', () => {
  it('lists, adds and removes keys', async () => {
    db.securityKeys = [{ id: 'key-0', label: 'Desk key', sign_count: 1 }]
    signIn()
    fakeKeys({ create: vi.fn().mockResolvedValue(attestation) })
    const user = userEvent.setup()
    renderApp('/me')

    expect(await screen.findByText('Desk key')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Key name'), 'Laptop')
    await user.click(screen.getByRole('button', { name: 'Add security key' }))
    expect(await screen.findByText('Laptop')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Remove Desk key' }))
    await waitFor(() => expect(screen.queryByText('Desk key')).not.toBeInTheDocument())
    expect(db.securityKeys.map((k) => k.label)).toEqual(['Laptop'])
  })

  it('shows a message when the request is cancelled', async () => {
    signIn()
    const cancelled = new Error('denied')
    cancelled.name = 'NotAllowedError'
    fakeKeys({ create: vi.fn().mockRejectedValue(cancelled) })
    const user = userEvent.setup()
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'Add security key' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('cancelled or timed out')
    expect(db.securityKeys).toHaveLength(0)
  })

  it('explains unsupported browsers instead of offering to add a key', async () => {
    signIn()
    renderApp('/me')
    expect(await screen.findByText('No security key registered.')).toBeInTheDocument()
    expect(screen.getByText('This browser cannot use security keys.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add security key' })).not.toBeInTheDocument()
  })
})

describe('second factor with a security key', () => {
  const assertion = {
    id: 'mock-assertion',
    rawId: new Uint8Array([1]).buffer,
    type: 'public-key',
    response: {
      authenticatorData: new Uint8Array([1]).buffer,
      clientDataJSON: new Uint8Array([2]).buffer,
      signature: new Uint8Array([3]).buffer,
      userHandle: null,
    },
    getClientExtensionResults: () => ({}),
  }

  async function loginAs(user: ReturnType<typeof userEvent.setup>) {
    await user.type(await screen.findByLabelText('Username'), 'mfakey')
    await user.type(screen.getByLabelText('Password'), 'secret')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
  }

  it('signs in with the key', async () => {
    fakeKeys({ get: vi.fn().mockResolvedValue(assertion) })
    const user = userEvent.setup()
    renderApp('/login')
    await loginAs(user)
    await user.click(await screen.findByRole('button', { name: 'Use security key' }))
    await waitFor(() => expect(db.session.pending).toBeNull())
    expect(db.session.user).toBe('mfa')
  })

  it('reports a cancelled prompt and can fall back to the authenticator', async () => {
    const cancelled = new Error('denied')
    cancelled.name = 'NotAllowedError'
    fakeKeys({ get: vi.fn().mockRejectedValue(cancelled) })
    const user = userEvent.setup()
    renderApp('/login')
    await loginAs(user)
    await user.click(await screen.findByRole('button', { name: 'Use security key' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('cancelled or timed out')
    await user.click(screen.getByRole('button', { name: 'Authenticator' }))
    expect(await screen.findByLabelText('Verification code')).toBeInTheDocument()
  })

  it('disables the key button when the browser lacks support', async () => {
    const user = userEvent.setup()
    renderApp('/login')
    await loginAs(user)
    const button = await screen.findByRole('button', { name: 'Use security key' })
    expect(button).toBeDisabled()
    expect(screen.getByText('This browser cannot use security keys.')).toBeInTheDocument()
  })
})

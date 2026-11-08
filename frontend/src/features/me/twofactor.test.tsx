import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { db } from '@/mocks/db'
import { renderApp, signIn } from '@/test/utils'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('authenticator app enrolment', () => {
  it('shows the QR code and secret, rejects a wrong code, then enables', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'Set up authenticator app' }))
    expect(await screen.findByRole('img', { name: /QR code/ })).toHaveAttribute(
      'src',
      expect.stringContaining('data:image/svg+xml'),
    )
    expect(screen.getByTestId('totp-secret')).toHaveTextContent('JBSWY3DPEHPK3PXP')
    expect(screen.getByRole('button', { name: 'Verify and enable' })).toBeDisabled()

    await user.type(screen.getByLabelText('Verification code'), '000000')
    await user.click(screen.getByRole('button', { name: 'Verify and enable' }))
    expect(await screen.findByText('Wrong code')).toBeInTheDocument()
    expect(db.totp.enabled).toBe(false)

    await user.clear(screen.getByLabelText('Verification code'))
    await user.type(screen.getByLabelText('Verification code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Verify and enable' }))
    expect(await screen.findByRole('button', { name: 'Disable authenticator app' })).toBeInTheDocument()
    expect(db.totp.enabled).toBe(true)
    expect(screen.queryByRole('img', { name: /QR code/ })).not.toBeInTheDocument()
    expect(screen.queryByTestId('totp-secret')).not.toBeInTheDocument()
  })

  it('can be cancelled without enabling anything', async () => {
    signIn()
    const user = userEvent.setup()
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'Set up authenticator app' }))
    await screen.findByTestId('totp-secret')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByTestId('totp-secret')).not.toBeInTheDocument()
    expect(db.totp.enabled).toBe(false)
  })

  it('asks for the password again when the server requires it, then retries', async () => {
    db.reauthFresh = false
    signIn()
    const user = userEvent.setup()
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'Set up authenticator app' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Confirm your password')
    await user.type(within(dialog).getByLabelText('Password'), 's3cret')
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    expect(await screen.findByTestId('totp-secret')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('disabling the authenticator app', () => {
  it('confirms first when it is the only second factor', async () => {
    db.totp = { enabled: true, recoveryCodes: 4, pending: false }
    signIn()
    const user = userEvent.setup()
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'Disable authenticator app' }))
    expect(await screen.findByRole('alertdialog')).toHaveTextContent('Turn off the second factor?')
    expect(db.totp.enabled).toBe(true)

    await user.click(screen.getByRole('button', { name: 'Disable and turn off' }))
    await waitFor(() => expect(db.totp.enabled).toBe(false))
    expect(await screen.findByRole('button', { name: 'Set up authenticator app' })).toBeInTheDocument()
    expect(await screen.findByText('No recovery codes.')).toBeInTheDocument()
  })

  it('does not ask when a security key remains', async () => {
    db.totp = { enabled: true, recoveryCodes: 0, pending: false }
    db.securityKeys = [{ id: 'key-0', label: 'Desk key', sign_count: 1 }]
    signIn()
    const user = userEvent.setup()
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'Disable authenticator app' }))
    await waitFor(() => expect(db.totp.enabled).toBe(false))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
})

describe('recovery codes', () => {
  it('cannot be generated without a second factor', async () => {
    signIn()
    renderApp('/me')
    expect(await screen.findByRole('button', { name: 'Generate recovery codes' })).toBeDisabled()
    expect(screen.getByText(/Set up an authenticator app or a security key/)).toBeInTheDocument()
  })

  it('are shown once, can be copied and downloaded', async () => {
    db.totp = { enabled: true, recoveryCodes: 0, pending: false }
    signIn()
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    const blobs: Blob[] = []
    const createObjectURL = vi.fn((b: Blob) => {
      blobs.push(b)
      return 'blob:codes'
    })
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }))
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    renderApp('/me')

    await user.click(await screen.findByRole('button', { name: 'Generate recovery codes' }))
    const list = await screen.findByRole('list', { name: 'Recovery codes' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(10)
    expect(screen.getByText(/shown only once/)).toBeInTheDocument()
    expect(await screen.findByText('10 recovery codes left.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Copy codes' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining('MOCKA-00000\nMOCKA-00001')))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Download .txt' }))
    expect(click).toHaveBeenCalled()
    expect(await blobs[0]?.text()).toContain('MOCKA-00009')

    await user.click(screen.getByRole('button', { name: 'I have saved them' }))
    expect(screen.queryByRole('list', { name: 'Recovery codes' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Regenerate recovery codes' })).toBeEnabled()
  })
})

describe('second factor at sign-in', () => {
  it('accepts a recovery code', async () => {
    const user = userEvent.setup()
    renderApp('/login')
    await user.type(await screen.findByLabelText('Username'), 'mfa')
    await user.type(screen.getByLabelText('Password'), 'secret')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await user.click(await screen.findByRole('button', { name: 'Recovery code' }))
    await user.type(screen.getByLabelText('Recovery code'), 'wrong-code')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(db.session.pending).toBe('mfa')

    await user.clear(screen.getByLabelText('Recovery code'))
    await user.type(screen.getByLabelText('Recovery code'), 'RECOVERY-0001')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    await waitFor(() => expect(db.session.pending).toBeNull())
    expect(db.session.user).toBe('mfa')
  })
})

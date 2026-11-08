import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  b64urlToBuffer,
  bufferToB64url,
  createCredential,
  getAssertion,
  WebAuthnClientError,
  webauthnSupported,
} from './webauthn'

function bytes(...v: number[]): ArrayBuffer {
  return new Uint8Array(v).buffer
}

function install(get: unknown, create: unknown = vi.fn()): void {
  vi.stubGlobal('PublicKeyCredential', class {})
  Object.defineProperty(navigator, 'credentials', { value: { get, create }, configurable: true })
}

afterEach(() => {
  vi.unstubAllGlobals()
  Object.defineProperty(navigator, 'credentials', { value: undefined, configurable: true })
})

describe('base64url helpers', () => {
  it('round-trips bytes without padding or url-unsafe characters', () => {
    const buf = bytes(251, 255, 190, 0, 1)
    const text = bufferToB64url(buf)
    expect(text).toBe('-_--AAE')
    expect(Array.from(new Uint8Array(b64urlToBuffer(text)))).toEqual([251, 255, 190, 0, 1])
  })
})

describe('webauthnSupported', () => {
  it('is false without the browser API', () => {
    expect(webauthnSupported()).toBe(false)
  })
  it('is true when credentials.get exists', () => {
    install(vi.fn())
    expect(webauthnSupported()).toBe(true)
  })
})

describe('getAssertion', () => {
  it('converts the options and the result', async () => {
    const get = vi.fn().mockResolvedValue({
      id: 'AQI',
      rawId: bytes(1, 2),
      type: 'public-key',
      response: {
        authenticatorData: bytes(3),
        clientDataJSON: bytes(4),
        signature: bytes(5),
        userHandle: null,
      },
      getClientExtensionResults: () => ({}),
    })
    install(get)
    const out = await getAssertion({
      challenge: 'AQI',
      allowCredentials: [{ id: 'AQI', type: 'public-key' }],
    })
    const arg = get.mock.calls[0]?.[0] as { publicKey: PublicKeyCredentialRequestOptions }
    expect(new Uint8Array(arg.publicKey.challenge as ArrayBuffer)).toEqual(new Uint8Array([1, 2]))
    expect(new Uint8Array(arg.publicKey.allowCredentials?.[0]?.id as ArrayBuffer)).toEqual(
      new Uint8Array([1, 2]),
    )
    expect(out).toMatchObject({
      rawId: 'AQI',
      response: { authenticatorData: 'Aw', clientDataJSON: 'BA', signature: 'BQ' },
    })
  })

  it('reports unsupported browsers', async () => {
    await expect(getAssertion({ challenge: 'AQI' })).rejects.toMatchObject({ reason: 'unsupported' })
  })

  it.each([
    ['NotAllowedError', 'cancelled'],
    ['AbortError', 'cancelled'],
    ['NotSupportedError', 'unsupported'],
    ['UnknownError', 'failed'],
  ])('maps %s to %s', async (name, reason) => {
    const err = new Error('x')
    err.name = name
    install(vi.fn().mockRejectedValue(err))
    const p = getAssertion({ challenge: 'AQI' })
    await expect(p).rejects.toBeInstanceOf(WebAuthnClientError)
    await expect(p).rejects.toMatchObject({ reason })
  })
})

describe('createCredential', () => {
  it('converts user id and exclusions, and serialises the attestation', async () => {
    const create = vi.fn().mockResolvedValue({
      id: 'AQI',
      rawId: bytes(1, 2),
      type: 'public-key',
      response: {
        attestationObject: bytes(7),
        clientDataJSON: bytes(8),
        getTransports: () => ['usb'],
      },
      getClientExtensionResults: () => ({}),
    })
    install(vi.fn(), create)
    const out = await createCredential({
      challenge: 'AQI',
      user: { id: 'AQI', name: 'u', displayName: 'U' },
      excludeCredentials: [{ id: 'AQI', type: 'public-key' }],
    })
    const arg = create.mock.calls[0]?.[0] as { publicKey: PublicKeyCredentialCreationOptions }
    expect(new Uint8Array(arg.publicKey.user.id as ArrayBuffer)).toEqual(new Uint8Array([1, 2]))
    expect(arg.publicKey.excludeCredentials).toHaveLength(1)
    expect(out).toMatchObject({
      response: { attestationObject: 'Bw', clientDataJSON: 'CA', transports: ['usb'] },
    })
  })

  it('treats a null credential as cancellation', async () => {
    install(vi.fn(), vi.fn().mockResolvedValue(null))
    await expect(
      createCredential({ challenge: 'AQI', user: { id: 'AQI', name: 'u', displayName: 'U' } }),
    ).rejects.toMatchObject({ reason: 'cancelled' })
  })
})

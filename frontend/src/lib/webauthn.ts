/**
 * Browser side of WebAuthn: base64url <-> ArrayBuffer conversion and thin wrappers around
 * `navigator.credentials`. Option and credential objects use the JSON shapes of the API.
 */

export type WebAuthnFailure = 'unsupported' | 'cancelled' | 'failed'

export class WebAuthnClientError extends Error {
  readonly reason: WebAuthnFailure

  constructor(reason: WebAuthnFailure, message?: string) {
    super(message ?? reason)
    this.name = 'WebAuthnClientError'
    this.reason = reason
  }
}

export function webauthnSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.PublicKeyCredential !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    typeof navigator.credentials?.get === 'function'
  )
}

export function b64urlToBuffer(value: string): ArrayBuffer {
  const padded = value
    .replace(/-/g, '+')
    .replace(/_/g, '/')
    .padEnd(Math.ceil(value.length / 4) * 4, '=')
  const bin = atob(padded)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return bytes.buffer
}

export function bufferToB64url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf)
  let bin = ''
  for (const b of bytes) bin += String.fromCharCode(b)
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

interface DescriptorJson {
  id: string
  type: PublicKeyCredentialType
  transports?: AuthenticatorTransport[]
}

function descriptor(d: DescriptorJson): PublicKeyCredentialDescriptor {
  return { ...d, id: b64urlToBuffer(d.id) }
}

export interface RequestOptionsJson {
  challenge: string
  allowCredentials?: DescriptorJson[]
  [key: string]: unknown
}

export interface CreationOptionsJson {
  challenge: string
  user: { id: string; name: string; displayName: string }
  excludeCredentials?: DescriptorJson[]
  [key: string]: unknown
}

function mapError(e: unknown): WebAuthnClientError {
  if (e instanceof WebAuthnClientError) return e
  const name = e instanceof Error ? e.name : ''
  if (name === 'NotAllowedError' || name === 'AbortError') return new WebAuthnClientError('cancelled')
  if (name === 'NotSupportedError' || name === 'SecurityError')
    return new WebAuthnClientError('unsupported', e instanceof Error ? e.message : undefined)
  return new WebAuthnClientError('failed', e instanceof Error ? e.message : undefined)
}

function requireSupport(): void {
  if (!webauthnSupported()) throw new WebAuthnClientError('unsupported')
}

/** Ask the authenticator for an assertion; resolves to the JSON the API expects. */
export async function getAssertion(options: RequestOptionsJson): Promise<Record<string, unknown>> {
  requireSupport()
  try {
    const cred = (await navigator.credentials.get({
      publicKey: {
        ...(options as object),
        challenge: b64urlToBuffer(options.challenge),
        allowCredentials: options.allowCredentials?.map(descriptor),
      } as PublicKeyCredentialRequestOptions,
    })) as PublicKeyCredential | null
    if (!cred) throw new WebAuthnClientError('cancelled')
    const r = cred.response as AuthenticatorAssertionResponse
    return {
      id: cred.id,
      rawId: bufferToB64url(cred.rawId),
      type: cred.type,
      response: {
        authenticatorData: bufferToB64url(r.authenticatorData),
        clientDataJSON: bufferToB64url(r.clientDataJSON),
        signature: bufferToB64url(r.signature),
        ...(r.userHandle ? { userHandle: bufferToB64url(r.userHandle) } : {}),
      },
      clientExtensionResults: cred.getClientExtensionResults(),
    }
  } catch (e) {
    throw mapError(e)
  }
}

/** Create a new credential; resolves to the JSON the API expects. */
export async function createCredential(
  options: CreationOptionsJson,
): Promise<Record<string, unknown>> {
  requireSupport()
  try {
    const cred = (await navigator.credentials.create({
      publicKey: {
        ...(options as object),
        challenge: b64urlToBuffer(options.challenge),
        user: { ...options.user, id: b64urlToBuffer(options.user.id) },
        excludeCredentials: options.excludeCredentials?.map(descriptor),
      } as PublicKeyCredentialCreationOptions,
    })) as PublicKeyCredential | null
    if (!cred) throw new WebAuthnClientError('cancelled')
    const r = cred.response as AuthenticatorAttestationResponse
    return {
      id: cred.id,
      rawId: bufferToB64url(cred.rawId),
      type: cred.type,
      response: {
        attestationObject: bufferToB64url(r.attestationObject),
        clientDataJSON: bufferToB64url(r.clientDataJSON),
        transports: typeof r.getTransports === 'function' ? r.getTransports() : [],
      },
      clientExtensionResults: cred.getClientExtensionResults(),
    }
  } catch (e) {
    throw mapError(e)
  }
}

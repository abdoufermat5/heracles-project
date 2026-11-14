/**
 * Rules of the second-factor and security-key forms. The server applies the same ones
 * (`heracles.api.v2.auth`: `ReauthBody`, `TotpConfirmBody`, `WebAuthnRegisterBody`, and the
 * TOTP verifier of `heracles.auth.second_factor`), so a value refused here is refused there
 * and the other way round.
 */
import i18n from 'i18next'
import type { FieldErrors } from '@/lib/liveForm'

export const REAUTH_PASSWORD_MAX = 1024
export const REAUTH_CODE_MAX = 64
export const SECURITY_KEY_LABEL_MAX = 64

/** Six digits, the only code the server's TOTP verifier compares against the token. */
const SIX_DIGITS = /^\d{6}$/
/** A generated recovery code, such as `ABCDE-FGHJK`; the server ignores the separator's case. */
const RECOVERY_CODE = /^[A-Za-z0-9]{5}[- ]?[A-Za-z0-9]{5}$/

/** The TOTP method when the code is six digits, the recovery method otherwise. */
export function reauthMethod(code: string): 'totp' | 'recovery' {
  return SIX_DIGITS.test(code.trim()) ? 'totp' : 'recovery'
}

/** Why `code` cannot be checked yet, or `null`: six digits from the authenticator app. */
export function authenticatorCodeError(code: string): string | null {
  const text = code.trim()
  if (text === '') return i18n.t('validation.required')
  if (!SIX_DIGITS.test(text)) return i18n.t('reauth.codeInvalid')
  return null
}

export interface ReauthValues extends Record<string, unknown> {
  value: string
}

/**
 * The confirmation dialog: a password, or a code of an existing second factor (six digits
 * from the authenticator app, or one of the `ABCDE-FGHJK` recovery codes). The server
 * refuses an empty body and caps the password at 1024 characters and the code at 64.
 */
export function reauthErrors(v: ReauthValues, useCode: boolean): FieldErrors {
  const text = useCode ? v.value.trim() : v.value
  if (text === '') return { value: i18n.t('validation.required') }
  const max = useCode ? REAUTH_CODE_MAX : REAUTH_PASSWORD_MAX
  if (text.length > max) return { value: i18n.t('validation.maxLength', { count: max }) }
  if (useCode && !SIX_DIGITS.test(text) && !RECOVERY_CODE.test(text))
    return { value: i18n.t('reauth.codeInvalid') }
  return {}
}

/** The name of a security key: optional, at most 64 characters (the server's cap). */
export function securityKeyLabelError(label: string): string | null {
  if (label.trim().length > SECURITY_KEY_LABEL_MAX)
    return i18n.t('validation.maxLength', { count: SECURITY_KEY_LABEL_MAX })
  return null
}

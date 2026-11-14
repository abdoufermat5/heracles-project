/**
 * Rules of the setup wizard, the browser's copy of `heracles.setup.service.validate_directory`
 * and `_validate`: what is refused here is refused by the server too.
 */
import i18n from 'i18next'
import { checkFormat, matchesFormat } from '@/lib/formats'
import type { FieldErrors } from '@/lib/liveForm'
import { MIN_PASSWORD_LENGTH } from '@/lib/password'
import type { AdminInput, DirectoryInput } from './api'

export const LABEL_MAX = 80
export const NAME_MAX = 128
const t = (key: string, options?: Record<string, unknown>) => i18n.t(key, options)

const URI_RE = /^(?:ldaps?:\/\/(\[[0-9A-Fa-f:.]+\]|[^/:\s]+)(?::(\d+))?|ldapi:\/\/\S+)$/
const LOGIN_RE = /^[A-Za-z0-9._-]{1,64}$/
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

/** One or several space-separated directory URIs; `null` when they are usable. */
export function checkUri(text: string): string | null {
  const uris = text.trim().split(/\s+/).filter(Boolean)
  if (uris.length === 0) return t('validation.required')
  for (const uri of uris) {
    const found = URI_RE.exec(uri)
    if (!found) return t('wizard.errors.uri')
    const [, host, port] = found
    if (host && !host.startsWith('[') && !matchesFormat('hostname', host)) return t('wizard.errors.uriHost')
    if (port && !matchesFormat('port', port)) return checkFormat('port', port)
  }
  return null
}

export type DirectoryValues = DirectoryInput & Record<string, unknown>

/** `requireBase`: the base DN may stay empty only for the first connection test. */
export function directoryErrors(v: DirectoryValues, requireBase: boolean): FieldErrors {
  const out: FieldErrors = {}
  const uri = checkUri(v.uri.trim() === 'ldap://' ? '' : v.uri)
  if (uri) out.uri = uri
  const base = v.base_dn.trim()
  if (base === '') {
    if (requireBase) out.base_dn = t('validation.required')
  } else {
    const problem = checkFormat('dn', base)
    if (problem) out.base_dn = problem
  }
  const bind = v.bind_dn.trim()
  if (bind !== '') {
    const problem = checkFormat('dn', bind)
    if (problem) out.bind_dn = problem
    else if (v.bind_password === '') out.bind_password = t('wizard.errors.bindPassword')
  }
  const ca = (v.ca_file ?? '').trim()
  if (ca !== '') {
    const problem = checkFormat('abs_path', ca)
    if (problem) out.ca_file = problem
  }
  if (v.starttls && /^ldaps:\/\//i.test(v.uri.trim())) out.starttls = t('wizard.errors.starttls')
  if (v.label.trim().length > LABEL_MAX) out.label = t('validation.maxLength', { count: LABEL_MAX })
  return out
}

export type AdminValues = AdminInput & { confirm: string } & Record<string, unknown>

export function adminErrors(v: AdminValues): FieldErrors {
  const out: FieldErrors = {}
  const uid = v.uid.trim()
  if (uid === '') out.uid = t('validation.required')
  else if (!LOGIN_RE.test(v.uid)) out.uid = t('wizard.errors.login')
  for (const [key, value] of [
    ['given_name', v.given_name],
    ['surname', v.surname],
  ] as const) {
    const text = value.trim()
    if (text === '') out[key] = t('validation.required')
    else if (text.length > NAME_MAX) out[key] = t('validation.maxLength', { count: NAME_MAX })
  }
  const mail = v.mail.trim()
  if (mail === '') out.mail = t('validation.required')
  else if (!EMAIL_RE.test(mail)) out.mail = t('validation.email')
  if (v.password === '') out.password = t('validation.required')
  else if (v.password.length < MIN_PASSWORD_LENGTH)
    out.password = t('validation.minLength', { count: MIN_PASSWORD_LENGTH })
  else if (v.password !== v.confirm) out.confirm = t('validation.passwordMismatch')
  return out
}

/** The optional public address: a full http(s) URL with a host. */
export function publicUrlError(url: string): string | null {
  const text = url.trim()
  if (text === '') return null
  try {
    const parsed = new URL(text)
    if ((parsed.protocol === 'http:' || parsed.protocol === 'https:') && parsed.hostname !== '') return null
  } catch {
    /* not a URL */
  }
  return t('wizard.errors.publicUrl')
}

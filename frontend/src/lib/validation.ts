import i18n from 'i18next'
import type { FieldErrors, Resolver } from 'react-hook-form'
import { z } from 'zod'
import type { AttributeDescriptor, TypeDescriptor, Values } from '@/api/types'
import { allAttributes, isEmpty, type FormValues } from './objects'

const t = (key: string, opts?: Record<string, unknown>): string => i18n.t(key, opts)

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const PHONE_RE = /^\+?[0-9 ().-]{3,}$/

function scalarSchema(a: AttributeDescriptor): z.ZodType {
  const c = a.constraints ?? {}
  switch (a.kind) {
    case 'int':
    case 'float': {
      let n = a.kind === 'int' ? z.number({ error: t('validation.number') }).int(t('validation.integer')) : z.number({ error: t('validation.number') })
      if (c.min !== undefined) n = n.min(c.min, t('validation.min', { min: c.min }))
      if (c.max !== undefined) n = n.max(c.max, t('validation.max', { max: c.max }))
      return n
    }
    case 'boolean':
      return z.boolean()
    case 'select':
      return z.string().refine(
        (v) => !a.options || a.options.some((o) => o.value === v),
        t('validation.invalid'),
      )
    default: {
      let s = z.string()
      if (c.min_length) s = s.min(c.min_length, t('validation.minLength', { count: c.min_length }))
      if (c.max_length) s = s.max(c.max_length, t('validation.maxLength', { count: c.max_length }))
      if (c.pattern) {
        try {
          s = s.regex(new RegExp(c.pattern), t('validation.pattern'))
        } catch {
          /* ignore invalid pattern from the server */
        }
      }
      if (a.kind === 'email') s = s.regex(EMAIL_RE, t('validation.email'))
      if (a.kind === 'phone') s = s.regex(PHONE_RE, t('validation.phone'))
      if (a.kind === 'url')
        return s.refine((v) => {
          try {
            new URL(v)
            return true
          } catch {
            return false
          }
        }, t('validation.url'))
      return s
    }
  }
}

/** Validate one value; returns flat `subpath -> message` ("" is the attribute itself). */
export function validateAttribute(
  a: AttributeDescriptor,
  v: unknown,
  path = '',
  out: Record<string, string> = {},
): Record<string, string> {
  if (a.kind === 'hidden' || a.kind === 'display') return out
  const join = (k: string | number) => (path ? `${path}.${k}` : String(k))

  if (isEmpty(v) && !(a.kind === 'boolean' && v === false && !a.required)) {
    if (a.required && a.kind !== 'password' && a.kind !== 'boolean') out[path] = t('validation.required')
    return out
  }
  if (a.kind === 'composite') {
    const obj = (v ?? {}) as Values
    for (const f of a.fields ?? []) validateAttribute(f, obj[f.name], join(f.name), out)
    return out
  }
  if (a.kind === 'list' && a.item) {
    const item = a.item
    const items = Array.isArray(v) ? v : []
    items.forEach((it, i) => validateAttribute({ ...item, required: true }, it, join(i), out))
    return out
  }
  if (a.multivalued && a.kind !== 'multiselect' && Array.isArray(v)) {
    v.forEach((it, i) =>
      validateAttribute({ ...a, multivalued: false, required: true }, it, join(i), out),
    )
    return out
  }
  if (['object_ref', 'department', 'multiselect', 'image', 'file', 'password', 'date', 'datetime', 'text', 'postal_address'].includes(a.kind)) {
    // lightweight kinds: only length constraints for text-like values
    if (typeof v === 'string' && a.kind !== 'password') {
      const r = scalarSchema({ ...a, kind: 'string' }).safeParse(v)
      if (!r.success) out[path] = r.error.issues[0]?.message ?? t('validation.invalid')
    }
    if (a.kind === 'password' && typeof v === 'string' && v !== '') {
      const r = scalarSchema({ ...a, kind: 'string' }).safeParse(v)
      if (!r.success) out[path] = r.error.issues[0]?.message ?? t('validation.invalid')
    }
    return out
  }
  const r = scalarSchema(a).safeParse(v)
  if (!r.success) out[path] = r.error.issues[0]?.message ?? t('validation.invalid')
  return out
}

function setIn(obj: Record<string, unknown>, path: string, leaf: unknown): void {
  const keys = path.split('.')
  let cur: Record<string, unknown> = obj
  keys.forEach((k, i) => {
    if (i === keys.length - 1) {
      cur[k] = leaf
    } else {
      const next = cur[k]
      if (typeof next !== 'object' || next === null) cur[k] = {}
      cur = cur[k] as Record<string, unknown>
    }
  })
}

export function validateForm(
  desc: TypeDescriptor,
  values: FormValues,
  active: Record<string, boolean>,
): Record<string, string> {
  const flat: Record<string, string> = {}
  for (const tab of desc.tabs) {
    if (!active[tab.name]) continue
    for (const a of allAttributes(tab)) {
      const sub: Record<string, string> = {}
      validateAttribute(a, values[tab.name]?.[a.name], '', sub)
      for (const [k, msg] of Object.entries(sub)) {
        flat[`${tab.name}.${a.name}${k ? `.${k}` : ''}`] = msg
      }
      if (a.kind === 'password') {
        const pw = values[tab.name]?.[a.name]
        const conf = values[tab.name]?.[`${a.name}__confirm`]
        if (typeof pw === 'string' && pw !== '' && pw !== (conf ?? '')) {
          flat[`${tab.name}.${a.name}`] = t('validation.passwordMismatch')
        }
      }
    }
  }
  return flat
}

/** react-hook-form resolver validating against the TypeDescriptor. */
export function makeResolver(
  desc: TypeDescriptor,
  getActive: () => Record<string, boolean>,
): Resolver<FormValues> {
  return (values) => {
    const flat = validateForm(desc, values, getActive())
    if (Object.keys(flat).length === 0) return { values, errors: {} }
    const errors: Record<string, unknown> = {}
    for (const [k, message] of Object.entries(flat)) setIn(errors, k, { type: 'validate', message })
    return { values: {}, errors: errors as FieldErrors<FormValues> }
  }
}

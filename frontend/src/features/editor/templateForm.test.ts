import type { ObjectDetail, TypeDescriptor } from '@/api/types'
import { defaultValue, prefillFromSource } from '@/lib/objects'
import { db } from '@/mocks/db'
import {
  compactValues,
  emptyFieldValues,
  fieldsDescriptor,
  isTemplatable,
  maskRequestTabs,
  maskValuesFromDetail,
  templateCreateTabs,
} from './templateForm'

function userDesc(): TypeDescriptor {
  const d = db.descriptor('user')
  if (!d) throw new Error('no user descriptor')
  return d
}

describe('fieldsDescriptor', () => {
  it('keeps only the listed attributes, all required, matching names case-insensitively', () => {
    const fd = fieldsDescriptor(userDesc(), { main: ['givenname', 'sn'] })
    expect(fd.tabs.map((t) => t.name)).toEqual(['main'])
    const names = fd.tabs.flatMap((t) => t.sections.flatMap((s) => s.attributes.map((a) => a.name)))
    expect(names).toEqual(['givenName', 'sn'])
    expect(fd.tabs[0]?.sections.flatMap((s) => s.attributes).every((a) => a.required)).toBe(true)
  })

  it('asks undeclared names as plain text', () => {
    const fd = fieldsDescriptor(userDesc(), { main: ['givenName', 'ticket'] })
    const extra = fd.tabs[0]?.sections.find((s) => s.name === '__extra')
    expect(extra?.attributes).toEqual([
      { name: 'ticket', label: 'ticket', kind: 'string', required: true },
    ])
  })

  it('drops tabs with nothing to ask and makes optional tabs mandatory', () => {
    const fd = fieldsDescriptor(userDesc(), { posix: ['homeDirectory'] })
    expect(fd.tabs.map((t) => t.name)).toEqual(['posix'])
    expect(fd.tabs[0]?.optional).toBe(false)
    expect(fieldsDescriptor(userDesc(), {}).tabs).toEqual([])
  })
})

describe('values sent to the API', () => {
  it('compacts form values and builds the create tabs', () => {
    const values = {
      main: { givenName: 'John', sn: '', tags: [], pwd__confirm: 'x', flag: false },
      posix: {},
    }
    expect(compactValues(values)).toEqual({ main: { givenName: 'John', flag: false } })
    expect(templateCreateTabs(values)).toEqual({
      main: { active: true, values: { givenName: 'John', flag: false } },
    })
  })

  it('builds empty values from defaults', () => {
    const fd = fieldsDescriptor(userDesc(), { main: ['givenName', 'sn'] })
    expect(emptyFieldValues(fd, defaultValue)).toEqual({ main: { givenName: null, sn: null } })
  })
})

describe('template editor values', () => {
  it('hides computed, hidden, binary and virtual attributes', () => {
    const attrs = userDesc().tabs.flatMap((t) => t.sections.flatMap((s) => s.attributes))
    const byName = (n: string) => attrs.find((a) => a.name === n)
    expect(isTemplatable(byName('givenName')!)).toBe(true)
    expect(isTemplatable(byName('cn')!)).toBe(false) // display
    expect(isTemplatable(byName('jpegPhoto')!)).toBe(false) // image
    expect(isTemplatable(byName('base')!)).toBe(false) // department
    expect(isTemplatable({ name: 'roles', label: 'Roles', kind: 'string', stored: false } as never)).toBe(false)
  })

  it('round-trips a template detail and only sends set values on creation', () => {
    const desc = userDesc()
    const values = maskValuesFromDetail(desc, {
      main: { values: { uid: '%s[0,1]l|givenName%%l|sn%', employeeType: 'employee' } },
    })
    expect(values.main?.uid).toBe('%s[0,1]l|givenName%%l|sn%')
    const active = { main: true, posix: false }
    const created = maskRequestTabs(desc, values, active, false)
    expect(created.main?.values).toEqual({
      uid: '%s[0,1]l|givenName%%l|sn%',
      employeeType: 'employee',
    })
    expect(created.posix).toBeUndefined()
  })

  it('clears emptied values and deactivated optional tabs on update', () => {
    const desc = userDesc()
    const values = maskValuesFromDetail(desc, { main: { values: { uid: 'x' } } })
    values.main!.uid = ''
    const updated = maskRequestTabs(desc, values, { main: true, posix: false }, true)
    expect(updated.main?.values.uid).toBe('')
    expect(updated.posix).toEqual({ active: false, values: {} })
  })
})

describe('prefillFromSource', () => {
  it('empties identifying attributes and keeps the rest', () => {
    const desc = userDesc()
    const rec = db.all('user')[0]
    if (!rec) throw new Error('no user')
    const detail: ObjectDetail = db.detail(rec)
    const values = prefillFromSource(desc, detail)
    expect(values.main?.uid).toBeNull()
    expect(values.main?.mail).toBeNull()
    expect(values.main?.userPassword).toBeNull()
    expect(values.main?.sn).toBe(rec.tabs.main?.values.sn)
    expect(values.main?.givenName).toBe(rec.tabs.main?.values.givenName)
  })
})

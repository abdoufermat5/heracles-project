import { describe, expect, it, vi } from 'vitest'
import type { TFunction } from 'i18next'
import { buildPaletteActions, currentObjectOf, fuzzyScore, type ActionContext } from './paletteActions'

const t = ((k: string, o?: { label?: string }) => (o?.label ? `${k}:${o.label}` : k)) as unknown as TFunction

function ctx(over: Partial<ActionContext> = {}): ActionContext {
  return {
    t,
    can: { createUser: true, createGroup: true, acl: true },
    current: null,
    go: vi.fn(),
    toggleTheme: vi.fn(),
    switchLanguage: vi.fn(),
    signOut: vi.fn(),
    copyDn: vi.fn(),
    ...over,
  }
}

describe('palette actions', () => {
  it('offers creation, rights, theme, language and sign out', () => {
    const ids = buildPaletteActions(ctx()).map((a) => a.id)
    expect(ids).toEqual(['new-user', 'new-group', 'check-rights', 'theme', 'language', 'sign-out'])
  })

  it('leaves out what the caller cannot do', () => {
    const ids = buildPaletteActions(ctx({ can: { createUser: false, createGroup: false, acl: false } })).map((a) => a.id)
    expect(ids).toEqual(['theme', 'language', 'sign-out'])
  })

  it('adds audit log and copy DN on an object page', () => {
    const c = ctx({ current: { type: 'user', dn: 'uid=a,dc=x' } })
    const actions = buildPaletteActions(c)
    actions.find((a) => a.id === 'audit-object')?.run()
    actions.find((a) => a.id === 'copy-dn')?.run()
    expect(c.go).toHaveBeenCalledWith('/activity/audit', { search: { object: 'uid=a,dc=x' } })
    expect(c.copyDn).toHaveBeenCalledWith('uid=a,dc=x')
  })

  it('reads the current object from the pathname', () => {
    expect(currentObjectOf('/types/user/uid%3Da%2Cdc%3Dx')).toEqual({ type: 'user', dn: 'uid=a,dc=x' })
    expect(currentObjectOf('/types/user/new')).toBeNull()
    expect(currentObjectOf('/types/user')).toBeNull()
  })

  it('matches fuzzily and prefers contiguous matches', () => {
    expect(fuzzyScore('nwu', 'New user')).not.toBeNull()
    expect(fuzzyScore('zzz', 'New user')).toBeNull()
    expect(fuzzyScore('user', 'New user')).toBeGreaterThan(fuzzyScore('nwsr', 'New user') ?? 0)
  })
})

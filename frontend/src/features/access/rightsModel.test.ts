import { describe, expect, it } from 'vitest'
import en from '@/locales/en'
import type { AclRole, Catalog, RightsReport, RoleTemplate } from '@/features/admin/types'
import {
  blocksFromTemplate,
  explainReport,
  matrixFromRole,
  matrixSentences,
  matrixToTemplates,
  rowHas,
  setColumnAction,
  setRowActions,
  templateGrants,
  toggleRowAction,
} from './rightsModel'

const catalog: Catalog = {
  all: 'all',
  categories: [
    {
      category: 'user',
      label: 'Users',
      wildcard: 'user/0',
      objects: [
        {
          key: 'user/user',
          label: 'User account',
          type: 'user',
          attributes: [
            { name: 'sn', label: 'Surname' },
            { name: 'userPassword', label: 'Password' },
          ],
        },
        {
          key: 'user/posixAccount',
          label: 'Unix account',
          type: 'user',
          attributes: [{ name: 'loginShell', label: 'Shell' }],
        },
      ],
    },
    {
      category: 'group',
      label: 'Groups',
      wildcard: 'group/0',
      objects: [
        {
          key: 'group/group',
          label: 'Group',
          type: 'group',
          attributes: [{ name: 'cn', label: 'Name' }],
        },
      ],
    },
  ],
}

const ROLES_DN = 'ou=aclroles,dc=example,dc=com'

function translate(key: string, options: Record<string, unknown> = {}): string {
  const value = key
    .split('.')
    .reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en)
  if (typeof value !== 'string') return key
  return value.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options[name] ?? ''))
}

function manager(): AclRole {
  return {
    dn: `cn=manager,${ROLES_DN}`,
    cn: 'manager',
    description: 'Full management of user accounts',
    templates: [
      {
        index: 0,
        raw: '0:user/user;cmdrw,user/posixAccount;cmdrw',
        blocks: [
          { object: 'user/user', rights: 'cmdrw', attributes: [] },
          { object: 'user/posixAccount', rights: 'cmdrw', attributes: [] },
        ],
      },
    ],
  }
}

function selfPassword(): AclRole {
  return {
    dn: `cn=editownpwd,${ROLES_DN}`,
    cn: 'editownpwd',
    description: 'Own password',
    templates: [
      {
        index: 0,
        raw: '0:user/user;s#userPassword;rw',
        blocks: [
          {
            object: 'user/user',
            rights: 's',
            attributes: [{ name: 'userPassword', rights: 'rw' }],
          },
        ],
      },
    ],
  }
}

function advanced(): AclRole {
  return {
    dn: `cn=advanced,${ROLES_DN}`,
    cn: 'advanced',
    description: 'Unknown parts must survive',
    templates: [
      {
        index: 0,
        raw: '0:snapshot;t#entryCSN;s,user/user;rw#sn;t',
        blocks: [
          { object: 'snapshot', rights: 't', attributes: [{ name: 'entryCSN', rights: 's' }] },
          {
            object: 'user/user',
            rights: 'rw',
            attributes: [{ name: 'sn', rights: 't' }],
          },
        ],
      },
    ],
  }
}

describe('role matrix', () => {
  it('turns stored rights into the five plain actions and the own-entry flag', () => {
    const matrix = matrixFromRole(manager(), catalog)
    const rows = matrix.templates[0]?.rows ?? []
    const user = rows.find((row) => row.key === 'user/user')
    expect(user).toBeDefined()
    expect(rowHas(user!, 'view')).toBe(true)
    expect(rowHas(user!, 'edit')).toBe(true)
    expect(rowHas(user!, 'delete')).toBe(true)
    expect(rowHas(user!, 'move')).toBe(true)
    expect(rowHas(user!, 'create')).toBe(true)
    expect(rows.find((row) => row.key === 'group/group')?.rights).toBe('')

    const own = matrixFromRole(selfPassword(), catalog).templates[0]?.rows.find(
      (row) => row.key === 'user/user',
    )
    expect(own?.rights).toBe('s')
    expect(own?.attributes).toEqual([{ name: 'userPassword', rights: 'rw' }])
  })

  it('returns untouched templates byte for byte, raw spelling included', () => {
    for (const role of [manager(), selfPassword(), advanced()]) {
      const matrix = matrixFromRole(role, catalog)
      const templates = matrixToTemplates(matrix, role.templates)
      expect(templates).toEqual(role.templates)
    }
  })

  it('keeps unknown objects, unknown attributes and the template letter when a row changes', () => {
    const role = advanced()
    const matrix = matrixFromRole(role, catalog)
    const userRow = matrix.templates[0]?.rows.find((row) => row.key === 'user/user')
    expect(userRow).toBeDefined()
    const changed = {
      ...matrix,
      templates: matrix.templates.map((template) => ({
        ...template,
        rows: template.rows.map((row) => (row.key === 'user/user' ? toggleRowAction(row, 'view') : row)),
      })),
    }
    const [template] = matrixToTemplates(changed, role.templates)
    expect(template?.raw).toBeUndefined()
    expect(template?.blocks).toEqual([
      { object: 'snapshot', rights: 't', attributes: [{ name: 'entryCSN', rights: 's' }] },
      { object: 'user/user', rights: 'w', attributes: [{ name: 'sn', rights: 't' }] },
    ])
  })

  it('drops a block emptied by the user and appends a new object in catalog order', () => {
    const role = manager()
    const matrix = matrixFromRole(role, catalog)
    const cleared = {
      ...matrix,
      templates: matrix.templates.map((template) => ({
        ...template,
        rows: template.rows.map((row) =>
          row.key === 'user/posixAccount' ? setRowActions(row, false) : row,
        ),
      })),
    }
    const [withoutPosix] = matrixToTemplates(cleared, role.templates)
    expect(withoutPosix?.blocks).toEqual([{ object: 'user/user', rights: 'cmdrw', attributes: [] }])

    const granted = {
      ...matrix,
      templates: matrix.templates.map((template) => ({
        ...template,
        rows: template.rows.map((row) =>
          row.key === 'group/group' ? toggleRowAction(row, 'view') : row,
        ),
      })),
    }
    const [withGroup] = matrixToTemplates(granted, role.templates)
    expect(withGroup?.blocks.at(-1)).toEqual({ object: 'group/group', rights: 'r', attributes: [] })
  })

  it('toggles a whole row and a whole column without touching other letters', () => {
    const matrix = matrixFromRole(advanced(), catalog)
    const template = matrix.templates[0]
    if (!template) throw new Error('missing template')
    const row = template.rows.find((item) => item.key === 'snapshot')
    if (!row) throw new Error('missing row')
    expect(setRowActions(row, true).rights).toBe('rwcdmt')
    expect(setRowActions(row, false).rights).toBe('t')

    const rows = matrix.templates[0]?.rows ?? []
    const withView = setColumnAction(rows, 'view', true)
    expect(withView.every((item) => rowHas(item, 'view'))).toBe(true)
  })

  it('describes the role in plain sentences', () => {
    const sentences = matrixSentences(matrixFromRole(manager(), catalog), translate)
    expect(sentences).toContain('Can view, create, edit, delete and move User account')
    expect(sentences).toContain('Can view, create, edit, delete and move Unix account')

    const own = matrixSentences(matrixFromRole(selfPassword(), catalog), translate)
    expect(own).toEqual(['Password: read and change only (their own entry only)'])
  })

  it('serialises a template back to its stored blocks', () => {
    const template = matrixFromRole(manager(), catalog).templates[0]
    expect(blocksFromTemplate(template!)).toEqual([
      { object: 'user/user', rights: 'cmdrw', attributes: [] },
      { object: 'user/posixAccount', rights: 'cmdrw', attributes: [] },
    ])
  })
})

describe('explaining a rights report', () => {
  const helpdesk: AclRole = {
    dn: `cn=helpdesk,${ROLES_DN}`,
    cn: 'helpdesk',
    description: '',
    templates: [
      {
        index: 0,
        blocks: [
          { object: 'user/user', rights: 'rw', attributes: [{ name: 'userPassword', rights: 'w' }] },
          { object: 'group/group', rights: 'r', attributes: [] },
        ],
      },
    ],
  }
  const paris = 'ou=Paris,dc=example,dc=com'
  const report: RightsReport = {
    dn: paris,
    object: 'user/user',
    rights: 'rw',
    attributes: { userPassword: 'rw', sn: 'rw' },
    warnings: [],
    rules: [{ origin: paris, scope: 'subtree', blocks: ['group/group', 'user/user'] }],
    bootstrap_admin: false,
  }
  const assignments = [
    {
      dn: paris,
      assignments: [
        {
          index: 0,
          scope: 'subtree' as const,
          role: helpdesk.dn,
          role_name: 'helpdesk',
          members: [{ dn: 'cn=staff,ou=groups,dc=example,dc=com', kind: 'group' as const }],
        },
      ],
    },
  ]

  it('names the role and where it is assigned', () => {
    const [grant] = explainReport(report, [helpdesk], assignments, 'user/user', 'edit')
    expect(grant).toMatchObject({
      roleName: 'helpdesk',
      roleDn: helpdesk.dn,
      originDn: paris,
      scope: 'subtree',
      grants: true,
    })
  })

  it('says so when the assignment does not grant the action', () => {
    const [grant] = explainReport(report, [helpdesk], assignments, 'user/user', 'delete')
    expect(grant?.grants).toBe(false)
  })

  it('understands category wildcards and the everything block', () => {
    const wildcard: RoleTemplate = {
      index: 0,
      blocks: [{ object: 'user/0', rights: 'cmdrw', attributes: [] }],
    }
    expect(templateGrants(wildcard, 'user/user', 'view')).toBe(true)
    expect(templateGrants(wildcard, 'group/group', 'view')).toBe(false)
    const all: RoleTemplate = { index: 0, blocks: [{ object: 'all', rights: 'r', attributes: [] }] }
    expect(templateGrants(all, 'group/group', 'view')).toBe(true)
  })
})

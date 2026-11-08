import type {
  AclRole,
  Assignment,
  AssignmentScope,
  AttributeRights,
  Catalog,
  RightsBlock,
  RightsReport,
  RoleTemplate,
} from '@/features/admin/types'
import { hasRight, toggleRight } from '@/features/admin/rights'

/**
 * Translation between the stored ACL blocks and what people actually decide:
 *
 *   view / create / edit / delete / move, on this kind of object,
 *   optionally only on one's own entry, optionally with per-field exceptions.
 *
 * The stored format (`object;rights#attr;rights`) stays the source of truth.
 * Everything here is pure: a role's templates become a matrix, editing the
 * matrix gives blocks back, and a template that was not touched is returned
 * untouched (raw spelling, unknown rights letters, unknown objects included).
 */

export const ACTIONS = ['view', 'create', 'edit', 'delete', 'move'] as const
export type Action = (typeof ACTIONS)[number]

/** ACL letter behind each action. `t` and `s` stay out of the five columns. */
export const ACTION_LETTER: Record<Action, string> = {
  view: 'r',
  create: 'c',
  edit: 'w',
  delete: 'd',
  move: 'm',
}

/** The actions behind each right letter, for the advanced view. */
export const ALL_LETTERS = ['r', 'w', 'c', 'd', 'm', 't', 's'] as const

export type Translate = (key: string, options?: Record<string, unknown>) => string

export interface AttributeMeta {
  name: string
  label: string
}

export interface MatrixRow {
  /** ACL object key (`user/user`, `user/0`, `all`, or an unknown key). */
  key: string
  /** Object label from the catalog, or the key for unknown objects. */
  label: string
  /** Category the row belongs to; `all` and `other` are synthetic. */
  group: string
  groupLabel: string
  type?: string
  wildcard?: boolean
  /** Stored rights string, kept verbatim so unknown letters survive. */
  rights: string
  attributes: AttributeRights[]
  /** Attributes of the object as the catalog describes them. */
  attributesMeta: AttributeMeta[]
  /** The block this row was read from, if any. */
  original?: RightsBlock
  /** Position of the block in the stored template (to keep their order). */
  position?: number
}

export interface MatrixTemplate {
  index: number
  raw?: string
  ignored?: boolean
  reason?: string
  rows: MatrixRow[]
}

export interface Matrix {
  templates: MatrixTemplate[]
}

interface Seed {
  key: string
  label: string
  group: string
  groupLabel: string
  type?: string
  wildcard?: boolean
  attributesMeta: AttributeMeta[]
}

function objectSeeds(catalog: Catalog | undefined): Seed[] {
  if (!catalog) return []
  const seeds: Seed[] = [
    { key: catalog.all, label: '', group: 'all', groupLabel: '', attributesMeta: [] },
  ]
  for (const category of catalog.categories) {
    seeds.push({
      key: category.wildcard,
      label: category.label,
      group: category.category,
      groupLabel: category.label,
      wildcard: true,
      attributesMeta: [],
    })
    for (const object of category.objects) {
      seeds.push({
        key: object.key,
        label: object.label,
        group: category.category,
        groupLabel: category.label,
        type: object.type,
        attributesMeta: object.attributes.map((a) => ({ name: a.name, label: a.label })),
      })
    }
  }
  return seeds
}

function emptyRow(seed: Seed): MatrixRow {
  return {
    key: seed.key,
    label: seed.label,
    group: seed.group,
    groupLabel: seed.groupLabel,
    type: seed.type,
    wildcard: seed.wildcard,
    rights: '',
    attributes: [],
    attributesMeta: seed.attributesMeta,
  }
}

function matrixRow(block: RightsBlock, seed: Seed | undefined, position: number): MatrixRow {
  return {
    key: block.object,
    label: seed?.label || block.object,
    group: seed?.group ?? 'other',
    groupLabel: seed?.groupLabel ?? '',
    type: seed?.type,
    wildcard: seed?.wildcard,
    rights: block.rights,
    attributes: block.attributes.map((a) => ({ ...a })),
    attributesMeta: seed?.attributesMeta ?? [],
    original: block,
    position,
  }
}

export function matrixFromTemplates(
  templates: RoleTemplate[],
  catalog: Catalog | undefined,
): Matrix {
  const seeds = objectSeeds(catalog)
  return {
    templates: templates.map((template) => {
      if (template.ignored) {
        return {
          index: template.index,
          raw: template.raw,
          ignored: true,
          reason: template.reason,
          rows: [],
        }
      }
      const used = new Set<number>()
      const rows = seeds.map((seed) => {
        const position = template.blocks.findIndex((b, i) => !used.has(i) && b.object === seed.key)
        if (position < 0) return emptyRow(seed)
        const block = template.blocks[position]
        if (!block) return emptyRow(seed)
        used.add(position)
        return matrixRow(block, seed, position)
      })
      template.blocks.forEach((block, position) => {
        if (used.has(position)) return
        // A block the catalog does not describe (plugin tab, `snapshot`, ...):
        // keep it visible so experts can still see and edit it.
        const seed: Seed = {
          key: block.object,
          label: block.object,
          group: 'other',
          groupLabel: '',
          attributesMeta: [],
        }
        rows.push(matrixRow(block, seed, position))
      })
      return { index: template.index, rows }
    }),
  }
}

export function matrixFromRole(role: AclRole | null, catalog: Catalog | undefined): Matrix {
  return matrixFromTemplates(role?.templates ?? [{ index: 0, blocks: [] }], catalog)
}

export interface RowGroup {
  id: string
  label: string
  rows: MatrixRow[]
}

/** Rows in the order people think of them: everything, each category, other. */
export function groupRows(rows: MatrixRow[], t: Translate): RowGroup[] {
  const groups = new Map<string, RowGroup>()
  for (const row of rows) {
    const existing = groups.get(row.group)
    if (existing) {
      existing.rows.push(row)
      continue
    }
    const label =
      row.group === 'all'
        ? t('accessUI.group.everything')
        : row.group === 'other'
          ? t('accessUI.group.other')
          : row.groupLabel
    groups.set(row.group, { id: row.group, label, rows: [row] })
  }
  if (groups.has('all')) {
    const all = groups.get('all') as RowGroup
    groups.delete('all')
    return [all, ...groups.values()]
  }
  return [...groups.values()]
}

// ── row editing ────────────────────────────────────────────────────────────

export function rowHas(row: MatrixRow, action: Action): boolean {
  return hasRight(row.rights, ACTION_LETTER[action])
}

export function rowSelf(row: MatrixRow): boolean {
  return hasRight(row.rights, 's')
}

export function rowHasContent(row: MatrixRow): boolean {
  return row.rights !== '' || row.attributes.length > 0
}

export function toggleRowAction(row: MatrixRow, action: Action): MatrixRow {
  return { ...row, rights: toggleRight(row.rights, ACTION_LETTER[action] as never) }
}

/** Row master switch: all five plain actions on, or off (other letters kept). */
export function setRowActions(row: MatrixRow, on: boolean): MatrixRow {
  let rights = row.rights
  for (const action of ACTIONS) {
    const letter = ACTION_LETTER[action]
    if (hasRight(rights, letter) !== on) rights = toggleRight(rights, letter as never)
  }
  return { ...row, rights }
}

/** Column switch: the same action on every row. */
export function setColumnAction(rows: MatrixRow[], action: Action, on: boolean): MatrixRow[] {
  return rows.map((row) => {
    if (on === rowHas(row, action)) return row
    return toggleRowAction(row, action)
  })
}

export function toggleRowSelf(row: MatrixRow): MatrixRow {
  return { ...row, rights: toggleRight(row.rights, 's') }
}

export function toggleLetter(row: MatrixRow, letter: string): MatrixRow {
  return { ...row, rights: toggleRight(row.rights, letter as never) }
}

export function setAttributeRight(row: MatrixRow, index: number, letter: 'r' | 'w', on: boolean): MatrixRow {
  const attributes = row.attributes.map((attribute, i) => {
    if (i !== index) return attribute
    const has = hasRight(attribute.rights, letter)
    if (has === on) return attribute
    return { ...attribute, rights: toggleRight(attribute.rights, letter as never) }
  })
  return { ...row, attributes }
}

export function toggleAttributeLetter(row: MatrixRow, index: number, letter: string): MatrixRow {
  return {
    ...row,
    attributes: row.attributes.map((attribute, i) =>
      i === index
        ? { ...attribute, rights: toggleRight(attribute.rights, letter as never) }
        : attribute,
    ),
  }
}

export function addAttribute(row: MatrixRow, name: string): MatrixRow {
  if (row.attributes.some((a) => a.name === name)) return row
  return { ...row, attributes: [...row.attributes, { name, rights: 'r' }] }
}

export function removeAttribute(row: MatrixRow, index: number): MatrixRow {
  return { ...row, attributes: row.attributes.filter((_, i) => i !== index) }
}

export function renameAttribute(row: MatrixRow, index: number, name: string): MatrixRow {
  return {
    ...row,
    attributes: row.attributes.map((a, i) => (i === index ? { ...a, name } : a)),
  }
}

function sameAttributes(a: AttributeRights[], b: AttributeRights[]): boolean {
  return a.length === b.length && a.every((x, i) => x.name === b[i]?.name && x.rights === b[i]?.rights)
}

function rowUnchanged(row: MatrixRow): boolean {
  return (
    !!row.original &&
    row.rights === row.original.rights &&
    sameAttributes(row.attributes, row.original.attributes)
  )
}

function blockFromRow(row: MatrixRow): RightsBlock {
  return {
    object: row.key,
    rights: row.rights,
    attributes: row.attributes
      .filter((a) => a.rights !== '')
      .map((a) => ({ name: a.name, rights: a.rights })),
  }
}

function sameBlocks(a: RightsBlock[], b: RightsBlock[]): boolean {
  return (
    a.length === b.length &&
    a.every(
      (block, i) =>
        block.object === b[i]?.object &&
        block.rights === b[i]?.rights &&
        sameAttributes(block.attributes, b[i]?.attributes ?? []),
    )
  )
}

/**
 * Blocks of one matrix template, in the stored order.
 *
 * Untouched blocks are emitted exactly as read (even empty ones); edited blocks
 * keep their position; a block emptied by the user is removed; new rows come
 * after the existing ones.
 */
export function blocksFromTemplate(template: MatrixTemplate): RightsBlock[] {
  const blocks: RightsBlock[] = []
  const originals = template.rows
    .filter((row) => row.original !== undefined)
    .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
  for (const row of originals) {
    if (rowUnchanged(row)) blocks.push(row.original as RightsBlock)
    else if (rowHasContent(row)) blocks.push(blockFromRow(row))
  }
  for (const row of template.rows) {
    if (!row.original && rowHasContent(row)) blocks.push(blockFromRow(row))
  }
  return blocks
}

/** Template to send back: untouched sources keep their raw spelling. */
export function templateToRole(template: MatrixTemplate, source?: RoleTemplate): RoleTemplate {
  if (template.ignored) {
    return (
      source ?? {
        index: template.index,
        raw: template.raw,
        ignored: true,
        reason: template.reason,
        blocks: [],
      }
    )
  }
  const blocks = blocksFromTemplate(template)
  if (source && !source.ignored && sameBlocks(blocks, source.blocks)) return source
  return { index: template.index, blocks }
}

export function matrixToTemplates(matrix: Matrix, sources: RoleTemplate[] = []): RoleTemplate[] {
  return matrix.templates.map((template, i) => templateToRole(template, sources[i]))
}

// ── plain language ─────────────────────────────────────────────────────────

export function rowObjectLabel(row: MatrixRow, t: Translate): string {
  if (row.group === 'all') return t('accessUI.summary.everything')
  if (row.wildcard) return t('accessUI.summary.allOfCategory', { category: row.groupLabel })
  return row.label || row.key
}

function joinWords(words: string[], t: Translate): string {
  if (words.length <= 1) return words[0] ?? ''
  return t('accessUI.summary.join', {
    head: words.slice(0, -1).join(t('accessUI.summary.comma')),
    last: words[words.length - 1] ?? '',
  })
}

export function actionWords(row: MatrixRow, t: Translate): string[] {
  return ACTIONS.filter((a) => rowHas(row, a)).map((a) => t(`accessUI.action.${a}`))
}

export function rowSentences(row: MatrixRow, t: Translate): string[] {
  const self = rowSelf(row)
  const object = rowObjectLabel(row, t)
  const suffix = self ? t('accessUI.summary.selfSuffix') : ''
  const words = actionWords(row, t)
  const out: string[] = []
  if (words.length > 0) {
    out.push(t('accessUI.summary.row', { actions: joinWords(words, t), object }) + suffix)
  } else if (self && row.attributes.length === 0) {
    out.push(t('accessUI.summary.selfOnly', { object }))
  }
  for (const attribute of row.attributes) {
    const token: string[] = []
    if (hasRight(attribute.rights, 'r')) token.push(t('accessUI.action.read'))
    if (hasRight(attribute.rights, 'w')) token.push(t('accessUI.action.change'))
    if (token.length === 0) continue
    const label =
      row.attributesMeta.find((a) => a.name === attribute.name)?.label || attribute.name
    out.push(
      t('accessUI.summary.attribute', {
        attribute: label,
        actions: joinWords(token, t),
      }) + suffix,
    )
  }
  return out
}

/** Deduplicated sentences describing what a matrix allows. */
export function matrixSentences(matrix: Matrix, t: Translate): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const template of matrix.templates) {
    if (template.ignored) continue
    for (const row of template.rows) {
      for (const sentence of rowSentences(row, t)) {
        if (seen.has(sentence)) continue
        seen.add(sentence)
        out.push(sentence)
      }
    }
  }
  return out
}

export function summarizeRole(role: AclRole, catalog: Catalog | undefined, t: Translate): string[] {
  return matrixSentences(matrixFromRole(role, catalog), t)
}

/** Objects a role grants something on, ignoring empty rows. */
export function roleObjectCount(role: AclRole): number {
  const keys = new Set<string>()
  for (const template of role.templates) {
    if (template.ignored) continue
    for (const block of template.blocks) {
      if (block.rights !== '' || block.attributes.length > 0) keys.add(block.object)
    }
  }
  return keys.size
}

// ── explaining an effective-rights report ──────────────────────────────────

export interface GrantExplanation {
  roleName: string
  roleDn: string
  originDn: string
  scope: AssignmentScope
  grants: boolean
}

function dnKey(dn: string): string {
  return dn.trim().toLowerCase()
}

function sameKey(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase()
}

function sameKeySet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  const left = a.map((k) => k.toLowerCase()).sort()
  const right = b.map((k) => k.toLowerCase()).sort()
  return left.every((k, i) => k === right[i])
}

function blockApplies(blockKey: string, objectKey: string): boolean {
  if (sameKey(blockKey, objectKey)) return true
  if (sameKey(blockKey, 'all')) return true
  if (blockKey.endsWith('/0')) {
    return objectKey.toLowerCase().startsWith(blockKey.slice(0, -1).toLowerCase())
  }
  return false
}

/** Whether one template carries the right asked for. */
export function templateGrants(template: RoleTemplate, objectKey: string, action: Action): boolean {
  if (template.ignored) return false
  const letter = ACTION_LETTER[action]
  return template.blocks.some(
    (block) => blockApplies(block.object, objectKey) && hasRight(block.rights, letter),
  )
}

/**
 * Which assignments produced the report, and whether they gave the asked right.
 *
 * Derived from the report's rules (the entry that carries the assignment and
 * the role blocks that applied) joined with the assignment list and roles.
 */
export function explainReport(
  report: RightsReport,
  roles: AclRole[],
  allAssignments: { dn: string; assignments: Assignment[] }[],
  objectKey: string,
  action: Action,
): GrantExplanation[] {
  const out: GrantExplanation[] = []
  const seen = new Set<string>()
  for (const rule of report.rules) {
    const entry = allAssignments.find((group) => dnKey(group.dn) === dnKey(rule.origin))
    const candidates = (entry?.assignments ?? []).filter((a) => !a.ignored && a.role)
    let matched = false
    for (const assignment of candidates) {
      const roleDn = assignment.role as string
      const role = roles.find((r) => dnKey(r.dn) === dnKey(roleDn))
      const templates = (role?.templates ?? []).filter((t) => !t.ignored)
      const structurally = templates.filter((t) =>
        sameKeySet(
          t.blocks.map((b) => b.object),
          rule.blocks,
        ),
      )
      const scope = assignment.scope ?? rule.scope
      if (templates.length > 0 && structurally.length === 0) continue
      const grants =
        structurally.length > 0
          ? structurally.some((t) => templateGrants(t, objectKey, action))
          : rule.blocks.some((key) => blockApplies(key, objectKey))
      const key = `${dnKey(roleDn)}|${dnKey(rule.origin)}|${scope}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({
        roleName: assignment.role_name ?? role?.cn ?? roleDn,
        roleDn,
        originDn: rule.origin,
        scope,
        grants,
      })
      matched = true
    }
    if (!matched) {
      const key = `?|${dnKey(rule.origin)}|${rule.scope}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({
        roleName: '',
        roleDn: '',
        originDn: rule.origin,
        scope: rule.scope,
        grants: rule.blocks.some((key) => blockApplies(key, objectKey)),
      })
    }
  }
  return out
}

/** The report's answer for one action. */
export function reportAllows(report: RightsReport, action: Action): boolean {
  return report.bootstrap_admin || hasRight(report.rights, ACTION_LETTER[action])
}

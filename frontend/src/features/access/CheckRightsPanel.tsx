import { Check, Minus, Search, ShieldCheck, ShieldX } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { useMe, useTree } from '@/api/hooks'
import { DepartmentPicker, ObjectRefPicker } from '@/components/fields/RefFields'
import { OrgPath } from '@/components/patterns'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { adminApi } from '@/features/admin/api'
import { useAllAssignments, useCatalog, useRoles } from '@/features/admin/hooks'
import type { TreeNode } from '@/api/types'
import type { RightsReport } from '@/features/admin/types'
import { orgPath } from '@/lib/dn'
import { useTechnicalDetails } from '@/lib/preferences'
import { rdnValue } from '@/lib/objects'
import { cn } from '@/lib/utils'
import {
  ACTIONS,
  type Action,
  explainReport,
  reportAllows,
  type GrantExplanation,
} from './rightsModel'

function isAction(value: string): value is Action {
  return (ACTIONS as readonly string[]).includes(value)
}

export function CheckRightsPanel() {
  const { t } = useTranslation()
  const technical = useTechnicalDetails()
  const { data: me } = useMe()
  const { data: tree } = useTree()
  const { data: catalog } = useCatalog()
  const { data: roles } = useRoles()
  const { data: allAssignments } = useAllAssignments()
  const [user, setUser] = useState<string | null>(null)
  const [action, setAction] = useState<Action>('view')
  const [objectKey, setObjectKey] = useState('user/user')
  const [department, setDepartment] = useState<string | null>(null)
  const [report, setReport] = useState<RightsReport | null>(null)
  const [busy, setBusy] = useState(false)

  const target = department ?? me?.base ?? ''
  const object = catalog?.categories.flatMap((category) => category.objects).find(
    (item) => item.key === objectKey,
  )
  const whereLabel =
    orgPath(target, me?.base, true).join(' › ') || treeLabel(tree, target) || t('patterns.topLevel')
  const personName = user ? rdnValue(user) : ''
  const objectLabel = object?.label ?? t('accessUI.check.unknown')

  const run = async () => {
    if (!user) return
    setBusy(true)
    try {
      setReport(
        await adminApi.checkRights({
          user,
          dn: target,
          object: objectKey,
          attributes: object?.attributes.map((attribute) => attribute.name) ?? [],
        }),
      )
    } catch (error) {
      toast.error(isApiError(error) ? error.message : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const allowed = report ? reportAllows(report, action) : false
  const explanations = useMemo(
    () =>
      report
        ? explainReport(report, roles ?? [], allAssignments ?? [], objectKey, action)
        : [],
    [report, roles, allAssignments, objectKey, action],
  )
  const granting = explanations.filter((grant) => grant.grants)
  const attributeLabels = new Map(
    (object?.attributes ?? []).map((attribute) => [attribute.name, attribute.label] as const),
  )

  return (
    <div className="space-y-4">
      <p className="max-w-3xl text-body text-muted-foreground">{t('accessUI.check.help')}</p>

      <form
        className="space-y-4 rounded-lg border bg-card p-4 md:p-5"
        onSubmit={(event) => {
          event.preventDefault()
          void run()
        }}
      >
        <h2 className="text-lead font-semibold text-foreground">{t('accessUI.check.question')}</h2>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="space-y-1">
            <Label htmlFor="check-who">{t('accessUI.check.who')}</Label>
            <ObjectRefPicker
              id="check-who"
              refType="user"
              selected={user ? [user] : []}
              label={user ? rdnValue(user) : t('accessUI.check.chooseWho')}
              onPick={setUser}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="check-action">{t('accessUI.check.action')}</Label>
            <Select
              value={action}
              onValueChange={(value) => {
                if (isAction(value)) setAction(value)
              }}
            >
              <SelectTrigger id="check-action" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ACTIONS.map((item) => (
                  <SelectItem key={item} value={item}>
                    {t(`accessUI.action.${item}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="check-object">{t('accessUI.check.object')}</Label>
            <Select value={objectKey} onValueChange={setObjectKey}>
              <SelectTrigger id="check-object" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {catalog?.categories.map((category) => (
                  <SelectGroup key={category.category}>
                    <SelectLabel>{category.label}</SelectLabel>
                    {category.objects.map((item) => (
                      <SelectItem key={item.key} value={item.key}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="check-where">{t('accessUI.check.where')}</Label>
            <DepartmentPicker id="check-where" value={target || null} onChange={setDepartment} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" size="sm" disabled={!user || busy}>
            <Search />
            {t('accessUI.check.run')}
          </Button>
          {!user && (
            <p className="text-caption text-muted-foreground">{t('accessUI.check.pickUser')}</p>
          )}
        </div>
      </form>

      {report && (
        <section
          aria-live="polite"
          aria-label={t('accessUI.check.effective')}
          className={cn(
            'rounded-lg border p-4 md:p-5',
            allowed
              ? 'border-success/30 bg-success-soft'
              : 'border-destructive/30 bg-destructive-soft',
          )}
        >
          <div className="flex items-start gap-3">
            {allowed ? (
              <ShieldCheck className="mt-0.5 size-5 shrink-0 text-success" aria-hidden />
            ) : (
              <ShieldX className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
            )}
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <h3
                  className={cn(
                    'text-lead font-semibold',
                    allowed ? 'text-success' : 'text-destructive',
                  )}
                >
                  {allowed ? t('accessUI.check.yesTitle') : t('accessUI.check.noTitle')}
                </h3>
              </div>
              <p className="text-body text-foreground">
                {allowed
                  ? t('accessUI.check.yesSentence', {
                      name: personName,
                      action: t(`accessUI.action.${action}`),
                      object: objectLabel,
                      where: whereLabel,
                    })
                  : t('accessUI.check.noSentence', {
                      name: personName,
                      action: t(`accessUI.action.${action}`),
                      object: objectLabel,
                      where: whereLabel,
                    })}
              </p>
              {report.bootstrap_admin && (
                <p className="text-small font-medium text-foreground">
                  {t('accessUI.check.superAdmin')}
                </p>
              )}

              {!report.bootstrap_admin &&
                (granting.length > 0 ? (
                  <ul className="space-y-1.5">
                    {granting.map((grant) => (
                      <GrantLine
                        key={`${grant.roleDn}|${grant.originDn}|${grant.scope}`}
                        grant={grant}
                        baseDn={me?.base}
                      />
                    ))}
                  </ul>
                ) : allowed ? (
                  <p className="text-small text-foreground">
                    {t('accessUI.check.explanationUnknown')}
                  </p>
                ) : (
                  <p className="text-small text-foreground">
                    {t('accessUI.check.noGrant')}
                    {report.rules.length === 0 && ` ${t('accessUI.check.noRules')}`}
                  </p>
                ))}
            </div>
          </div>

          <div className="mt-4 space-y-3 border-t border-current/10 pt-3">
            <div>
              <p className="text-small font-medium text-foreground">
                {t('accessUI.check.actionsGranted')}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {ACTIONS.filter((item) => reportAllows(report, item)).length === 0 ? (
                  <span className="text-small text-muted-foreground">
                    {t('accessUI.check.noneGranted')}
                  </span>
                ) : (
                  ACTIONS.filter((item) => reportAllows(report, item)).map((item) => (
                    <span
                      key={item}
                      className="inline-flex items-center gap-1 rounded-full border border-success/25 bg-card px-2 py-0.5 text-caption font-medium text-success"
                    >
                      <Check className="size-3" aria-hidden />
                      {t(`accessUI.action.${item}`)}
                    </span>
                  ))
                )}
              </div>
            </div>

            {report.warnings.length > 0 && (
              <div>
                <p className="text-small font-medium text-foreground">
                  {t('accessUI.check.warnings')}
                </p>
                <ul className="mt-1 space-y-1 text-small text-warning">
                  {report.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            )}

            <details className="text-small">
              <summary className="cursor-pointer font-medium text-foreground">
                {t('accessUI.check.attributeRights')}
              </summary>
              {Object.keys(report.attributes).length === 0 ? (
                <p className="mt-2 text-muted-foreground">{t('accessUI.check.noAttributes')}</p>
              ) : (
                <table className="mt-2 w-full">
                  <tbody>
                    {Object.entries(report.attributes).map(([name, rights]) => (
                      <tr key={name} className="border-t">
                        <td className="py-1.5">
                          {attributeLabels.get(name) ?? name}
                          {technical && (
                            <span className="ml-2 font-mono text-caption text-muted-foreground">
                              {name}
                            </span>
                          )}
                        </td>
                        <td className="py-1.5 text-right font-mono">
                          {rights || t('accessUI.check.noneGranted')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </details>

            <details className="text-small">
              <summary className="cursor-pointer font-medium text-foreground">
                {t('accessUI.check.details')}
              </summary>
              {explanations.length === 0 ? (
                <p className="mt-2 text-muted-foreground">{t('accessUI.check.rulesEmpty')}</p>
              ) : (
                <ul className="mt-2 space-y-1.5">
                  {explanations.map((grant, index) => (
                    <li
                      key={`${grant.roleDn}|${grant.originDn}|${index}`}
                      className="flex flex-wrap items-center gap-1.5"
                    >
                      {grant.grants ? (
                        <Check className="size-3.5 text-success" aria-hidden />
                      ) : (
                        <Minus className="size-3.5 text-muted-foreground" aria-hidden />
                      )}
                      <span>{grant.roleName || t('accessUI.check.becauseUnknownPrefix')}</span>
                      <OrgPath dn={grant.originDn} baseDn={me?.base} />
                      <span className="text-muted-foreground">
                        ({grant.scope === 'base'
                          ? t('accessUI.check.scopeBase')
                          : t('accessUI.check.scopeSubtree')})
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </details>
          </div>
        </section>
      )}
    </div>
  )
}

function treeLabel(nodes: TreeNode[] | undefined, dn: string): string | null {
  for (const node of nodes ?? []) {
    if (node.dn.toLowerCase() === dn.trim().toLowerCase()) return node.label
    const found = treeLabel(node.children, dn)
    if (found) return found
  }
  return null
}

function GrantLine({ grant, baseDn }: { grant: GrantExplanation; baseDn?: string }) {
  const { t } = useTranslation()
  return (
    <li className="flex flex-wrap items-center gap-1.5 text-small text-foreground">
      <Check className="size-3.5 text-success" aria-hidden />
      <span>
        {grant.roleName
          ? t('accessUI.check.becausePrefix', { role: grant.roleName })
          : t('accessUI.check.becauseUnknownPrefix')}
      </span>
      <OrgPath dn={grant.originDn} baseDn={baseDn} />
      <span className="text-muted-foreground">
        ({grant.scope === 'base' ? t('accessUI.check.scopeBase') : t('accessUI.check.scopeSubtree')})
      </span>
    </li>
  )
}

import { Search, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { useMe } from '@/api/hooks'
import { DepartmentPicker, ObjectRefPicker } from '@/components/fields/RefFields'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
import { rdnValue } from '@/lib/objects'
import { adminApi } from './api'
import { useCatalog } from './hooks'
import { rightsLabel } from './rights'
import type { RightsReport } from './types'

export function CheckRightsPanel() {
  const { t } = useTranslation()
  const { data: me } = useMe()
  const { data: catalog } = useCatalog()
  const [user, setUser] = useState<string | null>(null)
  const [dn, setDn] = useState<string | null>(null)
  const [object, setObject] = useState('user/user')
  const [report, setReport] = useState<RightsReport | null>(null)
  const [busy, setBusy] = useState(false)
  const target = dn ?? me?.base ?? ''

  const run = async () => {
    if (!user) return
    setBusy(true)
    const entry = catalog?.categories.flatMap((c) => c.objects).find((o) => o.key === object)
    try {
      setReport(
        await adminApi.checkRights({
          user,
          dn: target,
          object,
          attributes: entry?.attributes.map((a) => a.name) ?? [],
        }),
      )
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const attributeLabels = new Map(
    catalog?.categories
      .flatMap((c) => c.objects)
      .find((o) => o.key === object)
      ?.attributes.map((a) => [a.name, a.label] as const) ?? [],
  )

  return (
    <div className="space-y-4">
      <p className="text-[13px] text-muted-foreground">{t('acl.checkHelp')}</p>
      <div className="grid gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="chk-user">{t('acl.checkUser')}</Label>
          <ObjectRefPicker
            id="chk-user"
            refType="user"
            selected={user ? [user] : []}
            label={user ? rdnValue(user) : t('acl.chooseUser')}
            onPick={setUser}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="chk-target">{t('acl.checkTarget')}</Label>
          <DepartmentPicker id="chk-target" value={target} onChange={setDn} />
          <Input
            aria-label={t('acl.checkTargetDn')}
            className="mt-1 font-mono text-xs"
            value={dn ?? ''}
            placeholder={me?.base ?? ''}
            onChange={(e) => setDn(e.target.value || null)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="chk-object">{t('acl.object')}</Label>
          <Select value={object} onValueChange={setObject}>
            <SelectTrigger id="chk-object" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {catalog?.categories.map((c) => (
                <SelectGroup key={c.category}>
                  <SelectLabel>{c.label}</SelectLabel>
                  {c.objects.map((o) => (
                    <SelectItem key={o.key} value={o.key}>
                      {o.label} ({o.key})
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <Button size="sm" disabled={!user || busy} onClick={() => void run()}>
        <Search />
        {t('acl.checkRun')}
      </Button>

      {report && (
        <section aria-label={t('acl.checkResult')} className="space-y-3 rounded-md border bg-card p-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-muted-foreground" aria-hidden />
            <h3 className="text-sm font-semibold">{t('acl.checkResult')}</h3>
            <Badge variant="outline" className="font-mono" aria-label={t('acl.objectRights')}>
              {rightsLabel(report.rights)}
            </Badge>
          </div>
          {report.bootstrap_admin && (
            <p className="text-[13px] text-warning">{t('acl.bootstrapNote')}</p>
          )}
          {report.warnings.map((w) => (
            <p key={w} className="text-[13px] text-warning">
              {w}
            </p>
          ))}
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left">
                <th className="label-caps py-1 font-medium">{t('acl.attribute')}</th>
                <th className="label-caps py-1 font-medium">{t('acl.effective')}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(report.attributes).map(([name, rights]) => (
                <tr key={name} className="border-t">
                  <td className="py-1">
                    {attributeLabels.get(name) ?? name}
                    <span className="ml-2 font-mono text-[11px] text-muted-foreground">{name}</span>
                  </td>
                  <td className="py-1 font-mono">{rightsLabel(rights)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}

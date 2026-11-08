import { X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ObjectRefPicker } from '@/components/fields/RefFields'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { rdnValue } from '@/lib/objects'
import { useRoles } from './hooks'
import { memberDns } from './rights'
import type { Assignment, AssignmentScope } from './types'

const EVERYONE = '*'

export function AssignmentDialog({
  open,
  onOpenChange,
  initial,
  onSave,
  errors,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  initial: Assignment
  onSave: (a: Assignment) => void
  errors?: Record<string, string>
}) {
  const { t } = useTranslation()
  const { data: roles } = useRoles()
  const [scope, setScope] = useState<AssignmentScope>(initial.scope ?? 'subtree')
  const [role, setRole] = useState(initial.role ?? '')
  const [members, setMembers] = useState<string[]>(memberDns(initial))
  const [userFilter, setUserFilter] = useState(initial.user_filter ?? '')
  const [targetFilter, setTargetFilter] = useState(initial.target_filter ?? '')
  const everyone = members.includes(EVERYONE)

  const addMember = (dn: string) =>
    setMembers((m) => (m.includes(dn) ? m : [...m.filter((x) => x !== EVERYONE), dn]))

  const submit = () =>
    onSave({
      ...initial,
      ignored: false,
      scope,
      role,
      members,
      user_filter: userFilter.trim() || null,
      target_filter: targetFilter.trim() || null,
    })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('acl.assignment')}</DialogTitle>
          <DialogDescription>{t('acl.assignmentHelp')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="asg-role">{t('acl.role')}</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger id="asg-role" className="w-full" aria-invalid={!!errors?.role}>
                  <SelectValue placeholder={t('acl.chooseRole')} />
                </SelectTrigger>
                <SelectContent>
                  {role !== '' && !(roles ?? []).some((r) => r.dn === role) && (
                    <SelectItem value={role}>{rdnValue(role)}</SelectItem>
                  )}
                  {(roles ?? []).map((r) => (
                    <SelectItem key={r.dn} value={r.dn}>
                      {r.cn}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="asg-scope">{t('acl.scope')}</Label>
              <Select value={scope} onValueChange={(v) => setScope(v as AssignmentScope)}>
                <SelectTrigger id="asg-scope" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="subtree">{t('acl.scopeSubtree')}</SelectItem>
                  <SelectItem value="base">{t('acl.scopeBase')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>{t('acl.members')}</Label>
              <div className="flex items-center gap-2">
                <Switch
                  id="asg-everyone"
                  checked={everyone}
                  onCheckedChange={(on) => setMembers(on ? [EVERYONE] : [])}
                />
                <Label htmlFor="asg-everyone" className="text-[13px] font-normal">
                  {t('acl.everyone')}
                </Label>
              </div>
            </div>
            {errors?.members && <p className="text-xs text-destructive">{errors.members}</p>}
            {members.length > 0 && (
              <ul className="flex flex-wrap gap-1.5" aria-label={t('acl.members')}>
                {members.map((m) => (
                  <li key={m}>
                    <Badge variant="secondary" className="gap-1">
                      {m === EVERYONE ? t('acl.everyone') : rdnValue(m)}
                      <button
                        type="button"
                        aria-label={t('acl.removeMember', { member: m === EVERYONE ? t('acl.everyone') : rdnValue(m) })}
                        onClick={() => setMembers(members.filter((x) => x !== m))}
                      >
                        <X className="size-3" />
                      </button>
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
            {!everyone && (
              <div className="flex flex-wrap gap-2">
                {(['user', 'group', 'role'] as const).map((refType) => (
                  <ObjectRefPicker
                    key={refType}
                    id={`asg-add-${refType}`}
                    refType={refType}
                    selected={members}
                    label={t(`acl.add_${refType}`)}
                    onPick={addMember}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="asg-user-filter">{t('acl.userFilter')}</Label>
              <Input
                id="asg-user-filter"
                className="font-mono text-xs"
                placeholder="(department=Sales)"
                value={userFilter}
                aria-invalid={!!errors?.user_filter}
                onChange={(e) => setUserFilter(e.target.value)}
              />
              <p className="text-[11px] text-muted-foreground">{t('acl.userFilterHelp')}</p>
              {errors?.user_filter && <p className="text-xs text-destructive">{errors.user_filter}</p>}
            </div>
            <div className="space-y-1">
              <Label htmlFor="asg-target-filter">{t('acl.targetFilter')}</Label>
              <Input
                id="asg-target-filter"
                className="font-mono text-xs"
                placeholder="(manager=%dn%)"
                value={targetFilter}
                aria-invalid={!!errors?.target_filter}
                onChange={(e) => setTargetFilter(e.target.value)}
              />
              <p className="text-[11px] text-muted-foreground">{t('acl.targetFilterHelp')}</p>
              {errors?.target_filter && (
                <p className="text-xs text-destructive">{errors.target_filter}</p>
              )}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button type="button" disabled={role === '' || members.length === 0} onClick={submit}>
            {t('common.ok')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

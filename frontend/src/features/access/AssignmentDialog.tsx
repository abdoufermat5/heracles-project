import { X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { DepartmentPicker, ObjectRefPicker } from '@/components/fields/RefFields'
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
import { useRoles } from '@/features/admin/hooks'
import type { Assignment, AssignmentScope } from '@/features/admin/types'
import { EVERYONE } from './peopleModel'

export function AssignmentDialog({
  open,
  onOpenChange,
  defaultDepartment,
  onSave,
  errors,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultDepartment: string | null
  onSave: (item: Assignment, department: string) => void
  errors?: Record<string, string>
}) {
  const { t } = useTranslation()
  const { data: roles } = useRoles()
  const [department, setDepartment] = useState<string | null>(defaultDepartment)
  const [role, setRole] = useState('')
  const [scope, setScope] = useState<AssignmentScope>('subtree')
  const [members, setMembers] = useState<string[]>([])
  const [everyone, setEveryone] = useState(false)
  const [userFilter, setUserFilter] = useState('')
  const [targetFilter, setTargetFilter] = useState('')
  const [localErrors, setLocalErrors] = useState<Record<string, string>>({})

  const addMember = (dn: string) =>
    setMembers((current) => (current.includes(dn) ? current : [...current, dn]))

  const submit = () => {
    const next: Record<string, string> = {}
    if (department === null) next.where = t('accessUI.people.errors.where')
    if (role === '') next.role = t('accessUI.people.errors.role')
    if (!everyone && members.length === 0) next.members = t('accessUI.people.errors.members')
    setLocalErrors(next)
    if (Object.keys(next).length > 0) return
    onSave(
      {
        index: 0,
        ignored: false,
        scope,
        role,
        members: everyone ? [EVERYONE] : members,
        user_filter: userFilter.trim() || null,
        target_filter: targetFilter.trim() || null,
      },
      department as string,
    )
  }

  const error = (key: string) => localErrors[key] ?? errors?.[key]

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('accessUI.people.addTitle')}</DialogTitle>
          <DialogDescription>{t('accessUI.people.addHelp')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="asg-role">{t('accessUI.people.role')}</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger id="asg-role" className="w-full" aria-invalid={!!error('role')}>
                  <SelectValue placeholder={t('accessUI.people.chooseRole')} />
                </SelectTrigger>
                <SelectContent>
                  {(roles ?? []).map((item) => (
                    <SelectItem key={item.dn} value={item.dn}>
                      {item.cn}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {error('role') && <p className="text-caption text-destructive">{error('role')}</p>}
            </div>
            <div className="space-y-1">
              <Label htmlFor="asg-where">{t('accessUI.people.where')}</Label>
              <DepartmentPicker
                id="asg-where"
                value={department}
                onChange={setDepartment}
                invalid={!!error('where')}
              />
              <p className="text-caption text-muted-foreground">{t('accessUI.people.whereHelp')}</p>
              {error('where') && <p className="text-caption text-destructive">{error('where')}</p>}
            </div>
          </div>

          <div className="space-y-1">
            <Label htmlFor="asg-scope">{t('accessUI.people.scope')}</Label>
            <Select value={scope} onValueChange={(value) => setScope(value as AssignmentScope)}>
              <SelectTrigger id="asg-scope" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="subtree">{t('accessUI.people.scopeSubtree')}</SelectItem>
                <SelectItem value="base">{t('accessUI.people.scopeBase')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>{t('accessUI.people.who')}</Label>
              <div className="flex items-center gap-2">
                <Switch
                  id="asg-everyone"
                  checked={everyone}
                  onCheckedChange={(on) => {
                    setEveryone(on)
                    if (!on) setMembers([])
                  }}
                />
                <Label htmlFor="asg-everyone" className="text-body font-normal">
                  {t('accessUI.people.everyone')}
                </Label>
              </div>
            </div>
            <p className="text-caption text-muted-foreground">{t('accessUI.people.whoHelp')}</p>
            {error('members') && (
              <p className="text-caption text-destructive">{error('members')}</p>
            )}
            {members.length > 0 && (
              <ul className="flex flex-wrap gap-1.5" aria-label={t('accessUI.people.who')}>
                {members.map((member) => (
                  <li key={member}>
                    <Badge variant="secondary" className="gap-1">
                      {rdnValue(member)}
                      <button
                        type="button"
                        aria-label={t('accessUI.people.removeMember', { member: rdnValue(member) })}
                        onClick={() => setMembers(members.filter((dn) => dn !== member))}
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
                    label={t(
                      refType === 'user'
                        ? 'accessUI.people.addUser'
                        : refType === 'group'
                          ? 'accessUI.people.addGroup'
                          : 'accessUI.people.addRole',
                    )}
                    onPick={addMember}
                  />
                ))}
              </div>
            )}
          </div>

          <details className="rounded-md border px-3 py-2">
            <summary className="cursor-pointer text-small font-medium">
              {t('accessUI.people.advancedFilters')}
            </summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="asg-user-filter">{t('accessUI.people.userFilter')}</Label>
                <Input
                  id="asg-user-filter"
                  className="font-mono text-xs"
                  placeholder="(department=Sales)"
                  value={userFilter}
                  aria-invalid={!!error('user_filter')}
                  onChange={(event) => setUserFilter(event.target.value)}
                />
                <p className="text-caption text-muted-foreground">
                  {t('accessUI.people.userFilterHelp')}
                </p>
                {error('user_filter') && (
                  <p className="text-caption text-destructive">{error('user_filter')}</p>
                )}
              </div>
              <div className="space-y-1">
                <Label htmlFor="asg-target-filter">{t('accessUI.people.targetFilter')}</Label>
                <Input
                  id="asg-target-filter"
                  className="font-mono text-xs"
                  placeholder="(manager=%dn%)"
                  value={targetFilter}
                  aria-invalid={!!error('target_filter')}
                  onChange={(event) => setTargetFilter(event.target.value)}
                />
                <p className="text-caption text-muted-foreground">
                  {t('accessUI.people.targetFilterHelp')}
                </p>
                {error('target_filter') && (
                  <p className="text-caption text-destructive">{error('target_filter')}</p>
                )}
              </div>
            </div>
          </details>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button type="button" onClick={submit}>
            {t('accessUI.people.add')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

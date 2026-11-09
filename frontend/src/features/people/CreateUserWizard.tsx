import { Link, useNavigate } from '@tanstack/react-router'
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Check,
  ChevronRight,
  Copy,
  Eye,
  EyeOff,
  Loader2,
  Sparkles,
  User,
  Users,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '@/api/endpoints'
import { useObject, useObjectList, useTree, useTypeDescriptor } from '@/api/hooks'
import type { ObjectListItem, TreeNode } from '@/api/types'
import { ErrorState } from '@/components/ErrorState'
import { FactList, OrgPath, SectionCard } from '@/components/patterns'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { TemplateFillForm } from '@/features/editor/TemplateFillForm'
import { TemplatePicker } from '@/features/editor/TemplatePicker'
import { showTriggerOutput } from '@/features/editor/triggerOutput'
import { generatePassword, passwordStrength } from '@/lib/password'
import { useScope } from '@/lib/scope'
import { nameValue } from '@/lib/objects'
import { isApiError } from '@/api/client'
import { cn, initials } from '@/lib/utils'
import { suggestLogin } from './utils'

function flattenDepts(nodes: TreeNode[]): Array<{ dn: string; label: string }> {
  const out: Array<{ dn: string; label: string }> = []
  for (const n of nodes) {
    out.push({ dn: n.dn, label: n.label })
    out.push(...flattenDepts(n.children))
  }
  return out
}

interface CreateUserWizardProps {
  copyFrom?: string | null
}

type WizardStep = 1 | 2 | 3 | 4

export function CreateUserWizard({ copyFrom = null }: CreateUserWizardProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const scope = useScope()
  const tree = useTree()
  const desc = useTypeDescriptor('user')
  const sourceObj = useObject('user', copyFrom)

  const [step, setStep] = useState<WizardStep>(1)
  const [templateDn, setTemplateDn] = useState<string | null>(null)

  // Step 1: Identity
  const [givenName, setGivenName] = useState('')
  const [sn, setSn] = useState('')
  const [uid, setUid] = useState('')
  const [mail, setMail] = useState('')
  const [employeeType, setEmployeeType] = useState('employee')
  const [language, setLanguage] = useState('en')
  const [uidTouched, setUidTouched] = useState(false)

  // Step 2: Department & Groups
  const [department, setDepartment] = useState<string>(() => scope.base || '')
  const [selectedGroups, setSelectedGroups] = useState<string[]>([])

  // Step 3: Password
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [requirePasswordChange, setRequirePasswordChange] = useState(true)
  const [passwordExpiry, setPasswordExpiry] = useState('')
  const [passwordCopied, setPasswordCopied] = useState(false)

  // Submitting
  const [submitting, setSubmitting] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // Attributes the user type really has: send nothing else, offer nothing else
  const mainTab = desc.data?.tabs[0]
  const mainTabName = mainTab?.name ?? 'main'
  const known = new Set(mainTab?.sections.flatMap((s) => s.attributes.map((a) => a.name)) ?? [])
  const supportsForceChange = known.has('forcePasswordChange')
  const supportsExpiry = known.has('passwordExpiry')

  // Load available groups
  const groupsQuery = useObjectList('group', { scope: 'sub', limit: 100 })
  const availableGroups: ObjectListItem[] = groupsQuery.data?.pages.flatMap((p) => p.items) ?? []

  const effectiveDept = department || scope.base || tree.data?.[0]?.dn || ''

  // Prefill from source object if copying
  const [prevSource, setPrevSource] = useState<string | null>(null)
  if (sourceObj.data && prevSource !== copyFrom) {
    setPrevSource(copyFrom)
    const vals = (sourceObj.data.tabs.main?.values ?? {}) as Record<string, unknown>
    if (vals.givenName) setGivenName(String(vals.givenName))
    if (vals.sn) setSn(String(vals.sn))
    if (vals.employeeType) setEmployeeType(String(vals.employeeType))
    if (vals.preferredLanguage) setLanguage(String(vals.preferredLanguage))
    if (typeof vals.base === 'string') setDepartment(vals.base)
  }
  // Auto-suggest login and email when givenName or sn change
  const handleGivenNameChange = (val: string) => {
    setGivenName(val)
    if (!uidTouched) {
      const suggested = suggestLogin(val, sn)
      setUid(suggested)
    }
  }

  const handleSnChange = (val: string) => {
    setSn(val)
    if (!uidTouched) {
      const suggested = suggestLogin(givenName, val)
      setUid(suggested)
    }
  }

  const handleUidChange = (val: string) => {
    setUid(val)
    setUidTouched(true)
  }

  const handleGeneratePassword = () => {
    const pw = generatePassword(16)
    setPassword(pw)
    void navigator.clipboard?.writeText(pw).then(() => {
      setPasswordCopied(true)
      setTimeout(() => setPasswordCopied(false), 2000)
    })
  }

  const handleToggleGroup = (dn: string) => {
    setSelectedGroups((prev) =>
      prev.includes(dn) ? prev.filter((x) => x !== dn) : [...prev, dn],
    )
  }

  // Validations per step
  const canProceedStep1 = givenName.trim().length > 0 && sn.trim().length > 0 && uid.trim().length >= 2
  const canProceedStep2 = Boolean(effectiveDept)
  const canProceedStep3 = password.length === 0 || password.length >= 8

  // Submit and create user
  const handleCreate = async () => {
    setSubmitting(true)
    setCreateError(null)
    try {
      const fullName = `${givenName.trim()} ${sn.trim()}`.trim()
      const wanted: Record<string, unknown> = {
        givenName: givenName.trim(),
        sn: sn.trim(),
        cn: fullName,
        uid: uid.trim(),
        mail: mail.trim() || undefined,
        employeeType,
        preferredLanguage: language,
        base: effectiveDept,
        userPassword: password.trim() || null,
        forcePasswordChange: requirePasswordChange,
        passwordExpiry: passwordExpiry || null,
      }
      const values = Object.fromEntries(
        Object.entries(wanted).filter(([k, v]) => known.has(k) && v !== undefined),
      )
      const body = {
        base: effectiveDept,
        template: templateDn,
        tabs: { [mainTabName]: { active: true, values } },
      }

      const res = await api.createObject('user', body)
      const newDn = res.dn

      // Add to selected groups
      const failedGroups: string[] = []
      if (selectedGroups.length > 0) {
        for (const gDn of selectedGroups) {
          try {
            const gObj = await api.getObject('group', gDn)
            const membersRaw = gObj.tabs.main?.values.member
            const currentMembers: string[] = Array.isArray(membersRaw)
              ? (membersRaw as string[])
              : typeof membersRaw === 'string' && membersRaw
                ? [membersRaw]
                : []
            const updated = [...currentMembers, newDn]
            await api.patchObject('group', gDn, {
              tabs: {
                main: {
                  active: true,
                  values: { member: updated },
                },
              },
            })
          } catch {
            failedGroups.push(gDn)
          }
        }
      }
      if (failedGroups.length > 0)
        toast.warning(t('peopleUI.wizard.step4.groupsFailed', { count: failedGroups.length }))

      showTriggerOutput(res)
      toast.success(t('peopleUI.wizard.step4.success', { name: fullName }))
      void navigate({ to: '/types/$type/$dn', params: { type: 'user', dn: newDn } })
    } catch (err) {
      const fields = isApiError(err) ? Object.values(err.fields ?? {}) : []
      const message = err instanceof Error ? err.message : t('peopleUI.wizard.step4.failed')
      setCreateError([message, ...fields].join(' — '))
    } finally {
      setSubmitting(false)
    }
  }

  if (desc.isError) return <ErrorState error={desc.error} onRetry={() => void desc.refetch()} />

  if (templateDn && desc.data) {
    return (
      <div className="mx-auto max-w-4xl space-y-4 pb-24">
        <TemplatePicker type="user" selected={templateDn} onChange={setTemplateDn} />
        <TemplateFillForm
          desc={desc.data}
          templateDn={templateDn}
          onTemplateChange={setTemplateDn}
        />
      </div>
    )
  }

  const deptList = tree.data ? flattenDepts(tree.data) : []
  const selectedDeptLabel = deptList.find((d) => d.dn === effectiveDept)?.label ?? effectiveDept
  const pwStrength = passwordStrength(password)

  return (
    <div className="mx-auto max-w-3xl space-y-8 pb-24">
      {/* Header and Breadcrumb */}
      <div>
        <nav aria-label="Breadcrumbs" className="flex items-center gap-1.5 text-caption text-muted-foreground pb-2">
          <Link to="/types/$type" params={{ type: 'user' }} className="hover:text-foreground">
            Users
          </Link>
          <ChevronRight className="size-3.5" aria-hidden />
          <span className="text-foreground font-medium">{t('peopleUI.wizard.breadcrumb')}</span>
        </nav>
        <div className="flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-xl bg-primary-soft text-primary">
            <User className="size-6" />
          </div>
          <div>
            <h1 className="text-title font-semibold tracking-tight text-foreground">
              {t('peopleUI.wizard.title')}
            </h1>
            <p className="text-body text-muted-foreground">
              {step === 1 && t('peopleUI.wizard.step1.description')}
              {step === 2 && t('peopleUI.wizard.step2.description')}
              {step === 3 && t('peopleUI.wizard.step3.description')}
              {step === 4 && t('peopleUI.wizard.step4.description')}
            </p>
          </div>
        </div>
      </div>

      {/* Step Indicator */}
      <div className="grid grid-cols-4 gap-2">
        {(
          [
            { num: 1, label: t('peopleUI.wizard.steps.identity') },
            { num: 2, label: t('peopleUI.wizard.steps.department') },
            { num: 3, label: t('peopleUI.wizard.steps.credentials') },
            { num: 4, label: t('peopleUI.wizard.steps.review') },
          ] as const
        ).map((s) => (
          <div
            key={s.num}
            className={cn(
              'flex flex-col gap-1 border-t-2 pt-2 transition-colors',
              step === s.num
                ? 'border-primary text-foreground font-medium'
                : step > s.num
                  ? 'border-primary/50 text-muted-foreground'
                  : 'border-border text-muted-foreground/60',
            )}
          >
            <span className="text-caption">
              Step {s.num}
            </span>
            <span className="text-small truncate">{s.label}</span>
          </div>
        ))}
      </div>

      {/* Step 1: Identity */}
      {step === 1 && (
        <SectionCard title={t('peopleUI.wizard.step1.title')}>
          <div className="space-y-5">
            {/* Template picker */}
            <TemplatePicker
              type="user"
              selected={templateDn}
              onChange={setTemplateDn}
            />
            {sourceObj.data && desc.data && (
              <p className="rounded-md border bg-card p-3 text-body text-muted-foreground">
                {t('copy.prefilled', { name: nameValue(desc.data, sourceObj.data) })}
              </p>
            )}


            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="wiz-first-name" className="text-small font-medium">
                  {t('peopleUI.wizard.step1.givenName')} <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="wiz-first-name"
                  value={givenName}
                  onChange={(e) => handleGivenNameChange(e.target.value)}
                  placeholder="e.g. Alice"
                  autoFocus
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="wiz-last-name" className="text-small font-medium">
                  {t('peopleUI.wizard.step1.sn')} <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="wiz-last-name"
                  value={sn}
                  onChange={(e) => handleSnChange(e.target.value)}
                  placeholder="e.g. Martin"
                />
              </div>
            </div>

            {/* Display name preview */}
            {(givenName || sn) && (
              <div className="flex items-center gap-3 rounded-lg border bg-muted/30 p-3">
                <Avatar className="size-10">
                  <AvatarFallback className="bg-primary-soft text-small font-semibold text-primary">
                    {initials(`${givenName} ${sn}`)}
                  </AvatarFallback>
                </Avatar>
                <div>
                  <div className="font-medium text-foreground">{givenName} {sn}</div>
                  <div className="text-caption text-muted-foreground">{uid || 'username'} · {mail || 'email'}</div>
                </div>
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="wiz-uid" className="text-small font-medium">
                  {t('peopleUI.wizard.step1.uid')} <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="wiz-uid"
                  value={uid}
                  onChange={(e) => handleUidChange(e.target.value)}
                  placeholder="e.g. amartin"
                  className="font-mono"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="wiz-mail" className="text-small font-medium">
                  {t('peopleUI.wizard.step1.mail')}
                </Label>
                <Input
                  id="wiz-mail"
                  type="email"
                  value={mail}
                  onChange={(e) => {
                    setMail(e.target.value)
                  }}
                  
                />
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="wiz-type" className="text-small font-medium">
                  {t('peopleUI.wizard.step1.employeeType')}
                </Label>
                <Select value={employeeType} onValueChange={setEmployeeType}>
                  <SelectTrigger id="wiz-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="employee">{t('peopleUI.text.employee')}</SelectItem>
                    <SelectItem value="contractor">{t('peopleUI.text.contractor')}</SelectItem>
                    <SelectItem value="intern">{t('peopleUI.text.intern')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="wiz-lang" className="text-small font-medium">
                  {t('peopleUI.wizard.step1.language')}
                </Label>
                <Select value={language} onValueChange={setLanguage}>
                  <SelectTrigger id="wiz-lang">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="en">English (EN)</SelectItem>
                    <SelectItem value="fr">Français (FR)</SelectItem>
                    <SelectItem value="de">Deutsch (DE)</SelectItem>
                    <SelectItem value="es">Español (ES)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        </SectionCard>
      )}

      {/* Step 2: Department & Groups */}
      {step === 2 && (
        <SectionCard title={t('peopleUI.wizard.step2.title')}>
          <div className="space-y-6">
            {/* Department selection */}
            <div className="space-y-1.5">
              <Label className="text-small font-medium">
                {t('peopleUI.wizard.step2.department')} <span className="text-destructive">*</span>
              </Label>
              <Select value={effectiveDept} onValueChange={setDepartment}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={t('peopleUI.text.chooseDepartment')} />
                </SelectTrigger>
                <SelectContent>
                  {deptList.map((d) => (
                    <SelectItem key={d.dn} value={d.dn}>
                      <div className="flex items-center gap-2">
                        <Building2 className="size-3.5 text-muted-foreground" />
                        <span>{d.label}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {effectiveDept && (
                <p className="text-caption text-muted-foreground font-dn">
                  Location: <OrgPath dn={effectiveDept} />
                </p>
              )}
            </div>

            {/* Groups checklist */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-small font-medium">
                  {t('peopleUI.wizard.step2.groups')}
                </Label>
                <span className="text-caption text-muted-foreground">
                  {selectedGroups.length} selected
                </span>
              </div>
              <p className="text-caption text-muted-foreground">
                {t('peopleUI.wizard.step2.groupsHelp')}
              </p>

              {availableGroups.length === 0 ? (
                <p className="text-small text-muted-foreground italic">
                  {t('peopleUI.wizard.step2.noGroups')}
                </p>
              ) : (
                <div className="max-h-56 overflow-y-auto space-y-1.5 rounded-lg border bg-card p-2">
                  {availableGroups.map((g) => {
                    const name = String(g.values.cn ?? g.dn)
                    const desc = g.values.description ? String(g.values.description) : null
                    const isChecked = selectedGroups.includes(g.dn)
                    return (
                      <label
                        key={g.dn}
                        className={cn(
                          'flex items-center justify-between rounded-md p-2 hover:bg-muted/40 cursor-pointer transition-colors',
                          isChecked && 'bg-primary-soft/40',
                        )}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <Checkbox
                            checked={isChecked}
                            onCheckedChange={() => handleToggleGroup(g.dn)}
                            aria-label={name}
                          />
                          <div className="min-w-0">
                            <span className="font-medium text-small text-foreground">{name}</span>
                            {desc && (
                              <span className="text-caption text-muted-foreground block truncate">
                                {desc}
                              </span>
                            )}
                          </div>
                        </div>
                        <Users className="size-4 text-muted-foreground/60 shrink-0" aria-hidden />
                      </label>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </SectionCard>
      )}

      {/* Step 3: Password & Credentials */}
      {step === 3 && (
        <SectionCard title={t('peopleUI.wizard.step3.title')}>
          <div className="space-y-5">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label htmlFor="wiz-pw" className="text-small font-medium">
                  {t('peopleUI.wizard.step3.password')}
                </Label>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleGeneratePassword}
                  className="h-7 text-caption"
                >
                  <Sparkles className="size-3.5 mr-1 text-primary" />
                  {t('peopleUI.wizard.step3.generate')}
                </Button>
              </div>

              <div className="relative">
                <Input
                  id="wiz-pw"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t('peopleUI.text.passwordPlaceholder')}
                  className="font-mono pr-20 text-small"
                  autoComplete="new-password"
                />
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                  {password && (
                    <button
                      type="button"
                      onClick={() => {
                        void navigator.clipboard?.writeText(password).then(() => {
                          setPasswordCopied(true)
                          setTimeout(() => setPasswordCopied(false), 2000)
                        })
                      }}
                      className="p-1 text-muted-foreground hover:text-foreground"
                      title={t('peopleUI.wizard.step3.copy')}
                    >
                      {passwordCopied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setShowPassword((p) => !p)}
                    className="p-1 text-muted-foreground hover:text-foreground"
                  >
                    {showPassword ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                  </button>
                </div>
              </div>

              {/* Password strength meter */}
              {password && (
                <div className="flex items-center gap-2 pt-1 text-caption text-muted-foreground">
                  <div className="flex h-1.5 flex-1 gap-1">
                    {[1, 2, 3, 4].map((level) => (
                      <div
                        key={level}
                        className={cn(
                          'h-full flex-1 rounded-full transition-colors',
                          level <= pwStrength
                            ? pwStrength <= 2
                              ? 'bg-warning'
                              : 'bg-success'
                            : 'bg-muted',
                        )}
                      />
                    ))}
                  </div>
                  <span>
                    {pwStrength <= 2 ? t('peopleUI.wizard.step4.strengthModerate') : t('peopleUI.wizard.step4.strengthStrong')}
                  </span>
                </div>
              )}
            </div>

            {/* Force change checkbox (only when the user type supports it) */}
            {supportsForceChange && (
            <div className="flex items-start gap-2.5 rounded-lg border bg-card p-3">
              <Checkbox
                id="wiz-force-change"
                checked={requirePasswordChange}
                onCheckedChange={(c) => setRequirePasswordChange(c === true)}
                className="mt-0.5"
              />
              <div className="space-y-0.5">
                <Label htmlFor="wiz-force-change" className="font-medium cursor-pointer">
                  {t('peopleUI.wizard.step3.requireChange')}
                </Label>
                <p className="text-caption text-muted-foreground">
                  {t('peopleUI.wizard.step3.requireChangeHelp')}
                </p>
              </div>
            </div>
            )}

            {/* Optional expiry (only when the user type supports it) */}
            {supportsExpiry && (
            <div className="space-y-1.5">
              <Label htmlFor="wiz-expiry" className="text-small font-medium text-muted-foreground">
                {t('peopleUI.wizard.step3.passwordExpiry')}
              </Label>
              <Input
                id="wiz-expiry"
                type="date"
                value={passwordExpiry}
                onChange={(e) => setPasswordExpiry(e.target.value)}
                className="w-48 text-small"
              />
            </div>
            )}
          </div>
        </SectionCard>
      )}

      {/* Step 4: Review & Create */}
      {step === 4 && (
        <SectionCard title={t('peopleUI.wizard.step4.summary')}>
          <div className="space-y-6">
            <FactList
              columns={2}
              items={[
                { label: t('peopleUI.text.fullName'), value: `${givenName} ${sn}` },
                { label: t('peopleUI.text.login'), value: <span className="font-mono font-medium">{uid}</span> },
                { label: t('peopleUI.text.email'), value: mail || null },
                { label: t('peopleUI.text.employeeType'), value: t(`peopleUI.text.${employeeType}`) },
                { label: t('peopleUI.text.language'), value: language.toUpperCase() },
                { label: t('peopleUI.text.department'), value: selectedDeptLabel },
                {
                  label: t('peopleUI.text.assignedGroups'),
                  value: selectedGroups.length > 0 ? t('peopleUI.text.groupsSelected', { count: selectedGroups.length }) : null,
                },
                {
                  label: t('peopleUI.text.passwordSecurity'),
                  value: password
                    ? supportsForceChange && requirePasswordChange
                      ? t('peopleUI.text.passwordSetMustChange')
                      : t('peopleUI.text.passwordSet')
                    : t('peopleUI.text.passwordNotSet'),
                },
              ]}
            />
          </div>
        </SectionCard>
      )}

      {createError && step === 4 && (
        <p role="alert" className="rounded-md border border-destructive/30 bg-destructive-soft p-3 text-small text-destructive">
          {createError}
        </p>
      )}

      {/* Navigation Buttons */}
      <div className="flex items-center justify-between border-t pt-4">
        {step > 1 ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => setStep((s) => (s - 1) as WizardStep)}
            disabled={submitting}
          >
            <ArrowLeft className="size-4" />
            {t('peopleUI.wizard.back')}
          </Button>
        ) : (
          <Button asChild variant="ghost">
            <Link to="/types/$type" params={{ type: 'user' }}>
              {t('peopleUI.wizard.cancel')}
            </Link>
          </Button>
        )}

        {step < 4 ? (
          <Button
            type="button"
            disabled={
              (step === 1 && !canProceedStep1) ||
              (step === 2 && !canProceedStep2) ||
              (step === 3 && !canProceedStep3)
            }
            onClick={() => setStep((s) => (s + 1) as WizardStep)}
          >
            {t('peopleUI.wizard.next')}
            <ArrowRight className="size-4" />
          </Button>
        ) : (
          <Button
            type="button"
            disabled={submitting}
            onClick={() => void handleCreate()}
          >
            {submitting ? (
              <>
                <Loader2 className="animate-spin" aria-hidden />
                {t('peopleUI.wizard.step4.creating')}
              </>
            ) : (
              <>
                <Check className="size-4" />
                {t('peopleUI.wizard.step4.createButton')}
              </>
            )}
          </Button>
        )}
      </div>
    </div>
  )
}

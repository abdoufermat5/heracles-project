import { Info } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { usePatchObject } from '@/api/hooks'
import type { AttributeDescriptor, Me, ObjectDetail, TypeDescriptor } from '@/api/types'
import { FactList, SectionCard } from '@/components/patterns/SectionCard'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { attributeLabel } from '@/lib/labels'

/**
 * Personal details an employee looks at or keeps up to date, in this order. Only
 * the ones the user type actually has are shown; labels come from the server.
 */
const PERSONAL_ATTRIBUTES = [
  'mail',
  'telephoneNumber',
  'mobile',
  'description',
  'roomNumber',
  'l',
  'preferredLanguage',
  'employeeNumber',
] as const

function firstText(value: unknown): string {
  if (Array.isArray(value)) return typeof value[0] === 'string' ? value[0] : ''
  return typeof value === 'string' ? value : ''
}

/** The employee's own details, editable where the directory's rights allow it. */
export function ProfileSection({
  me,
  detail,
  descriptor,
}: {
  me: Me
  detail?: ObjectDetail
  descriptor?: TypeDescriptor
}) {
  const { t } = useTranslation()
  const patch = usePatchObject('user', me.dn)
  const [editing, setEditing] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  const mainTab = descriptor?.tabs[0]
  const tabName = mainTab?.name ?? 'main'
  const values = detail?.tabs[tabName]?.values ?? {}
  const rights = detail?.acl?.[tabName]?.attributes ?? {}

  const byName = new Map<string, AttributeDescriptor>()
  for (const section of mainTab?.sections ?? [])
    for (const attr of section.attributes) byName.set(attr.name, attr)

  const fields = PERSONAL_ATTRIBUTES.map((name) => byName.get(name)).filter(
    (a): a is AttributeDescriptor => a !== undefined,
  )
  const editable = fields.filter((a) => (rights[a.name] ?? '').includes('w'))

  const startEdit = () => {
    setDrafts(Object.fromEntries(editable.map((a) => [a.name, firstText(values[a.name])])))
    setEditing(true)
  }

  const save = async () => {
    const changed: Record<string, unknown> = {}
    for (const attr of editable) {
      const next = (drafts[attr.name] ?? '').trim()
      if (next === firstText(values[attr.name])) continue
      changed[attr.name] = attr.multivalued ? (next ? [next] : []) : next
    }
    if (Object.keys(changed).length === 0) {
      setEditing(false)
      return
    }
    try {
      await patch.mutateAsync({ tabs: { [tabName]: { active: true, values: changed } } })
      toast.success(t('settingsUI.portal.saveSuccess'))
      setEditing(false)
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    }
  }

  return (
    <SectionCard
      id="portal-profile"
      title={t('settingsUI.portal.profileTitle')}
      description={t('settingsUI.portal.profileSubtitle')}
      editable={editable.length > 0}
      editing={editing}
      saving={patch.isPending}
      onEdit={startEdit}
      onSave={() => void save()}
      onCancel={() => setEditing(false)}
    >
      {!detail ? (
        <div className="space-y-4">
          <FactList items={[{ label: t('settingsUI.portal.login'), value: me.uid }]} />
          <p className="flex items-start gap-2 rounded-md bg-muted/60 p-3 text-small text-muted-foreground">
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
            {t('settingsUI.portal.profileUnavailable')}
          </p>
        </div>
      ) : editing ? (
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            void save()
          }}
        >
          {editable.map((attr) => (
            <div key={attr.name} className="space-y-1.5">
              <Label htmlFor={`profile-${attr.name}`}>{attributeLabel(t, attr.name, attr.label)}</Label>
              <Input
                id={`profile-${attr.name}`}
                type={attr.name === 'mail' ? 'email' : attr.name.toLowerCase().includes('phone') || attr.name === 'mobile' ? 'tel' : 'text'}
                value={drafts[attr.name] ?? ''}
                onChange={(e) => setDrafts((d) => ({ ...d, [attr.name]: e.target.value }))}
              />
            </div>
          ))}
        </form>
      ) : (
        <FactList
          items={[
            { label: t('settingsUI.portal.login'), value: <span className="font-mono">{me.uid}</span> },
            ...fields.map((attr) => ({ label: attributeLabel(t, attr.name, attr.label), value: firstText(values[attr.name]) || null })),
          ]}
        />
      )}
    </SectionCard>
  )
}

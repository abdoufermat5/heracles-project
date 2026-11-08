import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { usePatchObject } from '@/api/hooks'
import type { Me, ObjectDetail, TypeDescriptor } from '@/api/types'
import { FactList, SectionCard } from '@/components/patterns/SectionCard'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export function ProfileSection({
  me,
  detail,
  descriptor: _descriptor,
}: {
  me: Me
  detail?: ObjectDetail
  descriptor?: TypeDescriptor
}) {
  const { t } = useTranslation()
  const patch = usePatchObject('user', me.dn)
  const [editing, setEditing] = useState(false)

  const mainValues = detail?.tabs.main?.values ?? {}
  const mainAcl = detail?.acl?.main?.attributes ?? {}

  // Current values
  const currentPhone = Array.isArray(mainValues.telephoneNumber)
    ? (mainValues.telephoneNumber[0] as string | undefined) ?? ''
    : typeof mainValues.telephoneNumber === 'string'
      ? mainValues.telephoneNumber
      : ''
  const currentTitle = typeof mainValues.description === 'string' ? mainValues.description : ''
  const currentLang = typeof mainValues.preferredLanguage === 'string' ? mainValues.preferredLanguage : 'en'

  // Form draft state
  const [phoneDraft, setPhoneDraft] = useState(currentPhone)
  const [titleDraft, setTitleDraft] = useState(currentTitle)
  const [langDraft, setLangDraft] = useState(currentLang)

  const canEditPhone = mainAcl.telephoneNumber === 'rw'
  const canEditTitle = mainAcl.description === 'rw'
  const canEditLang = mainAcl.preferredLanguage === 'rw'

  const hasEditable = canEditPhone || canEditTitle || canEditLang

  const startEdit = () => {
    setPhoneDraft(currentPhone)
    setTitleDraft(currentTitle)
    setLangDraft(currentLang)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
  }

  const saveEdit = async () => {
    const updatedValues: Record<string, unknown> = {}
    if (canEditPhone && phoneDraft !== currentPhone) {
      updatedValues.telephoneNumber = phoneDraft.trim() ? [phoneDraft.trim()] : []
    }
    if (canEditTitle && titleDraft !== currentTitle) {
      updatedValues.description = titleDraft.trim()
    }
    if (canEditLang && langDraft !== currentLang) {
      updatedValues.preferredLanguage = langDraft
    }

    if (Object.keys(updatedValues).length === 0) {
      setEditing(false)
      return
    }

    try {
      await patch.mutateAsync({
        tabs: {
          main: {
            active: true,
            values: updatedValues,
          },
        },
      })
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
      editable={hasEditable}
      editing={editing}
      saving={patch.isPending}
      onEdit={startEdit}
      onSave={() => void saveEdit()}
      onCancel={cancelEdit}
    >
      {editing ? (
        <form
          className="grid gap-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            void saveEdit()
          }}
        >
          {canEditTitle && (
            <div className="space-y-1.5">
              <Label htmlFor="profile-title">{t('settingsUI.portal.title')}</Label>
              <Input
                id="profile-title"
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                placeholder="Software Engineer, Product Manager, etc."
              />
            </div>
          )}

          {canEditPhone && (
            <div className="space-y-1.5">
              <Label htmlFor="profile-phone">{t('settingsUI.portal.phone')}</Label>
              <Input
                id="profile-phone"
                type="tel"
                value={phoneDraft}
                onChange={(e) => setPhoneDraft(e.target.value)}
                placeholder="+33 1 23 45 67 89"
              />
            </div>
          )}

          {canEditLang && (
            <div className="space-y-1.5">
              <Label htmlFor="profile-lang">{t('user.language')}</Label>
              <Select value={langDraft} onValueChange={setLangDraft}>
                <SelectTrigger id="profile-lang" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="en">English</SelectItem>
                  <SelectItem value="fr">Français</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
        </form>
      ) : (
        <FactList
          items={[
            {
              label: t('settingsUI.portal.login'),
              value: <span className="font-mono text-xs">{me.uid}</span>,
            },
            {
              label: t('settingsUI.portal.email'),
              value: `${me.uid}@example.com`,
            },
            {
              label: t('settingsUI.portal.title'),
              value: currentTitle || <span className="text-muted-foreground">—</span>,
            },
            {
              label: t('settingsUI.portal.phone'),
              value: currentPhone || <span className="text-muted-foreground">—</span>,
            },
            {
              label: t('user.language'),
              value: currentLang === 'fr' ? 'Français' : 'English',
            },
            {
              label: 'Employee ID',
              value: (
                <span className="font-mono text-xs text-muted-foreground">
                  {(mainValues.internalId as string | undefined) ?? 'EMP-0042'}
                </span>
              ),
            },
          ]}
        />
      )}
    </SectionCard>
  )
}

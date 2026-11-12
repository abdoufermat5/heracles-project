import { Link } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useMe, useObject, useTypeDescriptor } from '@/api/hooks'
import { Button } from '@/components/ui/button'
import { PageLayout } from '@/components/patterns'
import { Skeleton } from '@/components/ui/skeleton'
import { useCapabilities } from '@/features/admin/hooks'
import { SessionsPanel } from '@/features/me/SessionsPanel'
import { GroupsSection } from '@/features/portal/GroupsSection'
import { PasswordSection } from '@/features/portal/PasswordSection'
import { ProfileCard } from '@/features/portal/ProfileCard'
import { ProfileSection } from '@/features/portal/ProfileSection'
import { SecuritySection } from '@/features/portal/SecuritySection'
import { TechnicalDetailsSection } from '@/features/portal/TechnicalDetailsSection'
import { useTechnicalDetails } from '@/lib/preferences'

export function MePage() {
  const { t } = useTranslation()
  const { data: me, isPending: mePending } = useMe()
  const { data: caps } = useCapabilities()
  const technical = useTechnicalDetails()

  const userDn = me?.dn ?? null
  const { data: userObject, isPending: objectPending } = useObject('user', userDn)
  const { data: userDescriptor } = useTypeDescriptor('user')

  const scrollToSection = (sectionId: string) => {
    const el = document.getElementById(sectionId)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  if (mePending || objectPending) {
    return (
      <div className="space-y-6" aria-busy="true" aria-label={t('common.loading')}>
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-48 w-full rounded-xl" />
        <Skeleton className="h-48 w-full rounded-xl" />
      </div>
    )
  }

  if (!me) return null

  const mainValues = userObject?.tabs.main?.values ?? {}
  const title = typeof mainValues.description === 'string' ? mainValues.description : undefined
  const phone = Array.isArray(mainValues.telephoneNumber)
    ? (mainValues.telephoneNumber[0] as string | undefined)
    : typeof mainValues.telephoneNumber === 'string'
      ? mainValues.telephoneNumber
      : undefined
  const mail = typeof mainValues.mail === 'string' ? mainValues.mail : undefined
  const isConsoleUser = caps?.console ?? me.is_admin

  const body = (
    <>
      {/* Employee / User Overview Card */}
      <ProfileCard
        me={me}
        title={title}
        phone={phone}
        mail={mail}
        onNavigate={scrollToSection}
      />

      {/* Profile Details with Inline Edit for permitted fields */}
      <ProfileSection
        me={me}
        detail={userObject}
        descriptor={userDescriptor}
      />

      {/* Password Change Flow */}
      <PasswordSection
        userDn={me.dn}
        allowed={(userObject?.acl?.[userDescriptor?.tabs[0]?.name ?? 'main']?.attributes.userPassword ?? '').includes('w')}
      />

      {/* Guided 2FA and Security Keys Setup */}
      <SecuritySection />

      {/* Active sessions: devices signed in to this account */}
      <SessionsPanel />

      {/* My Groups (Read-only list) */}
      <GroupsSection />

      {/* Technical details (Visible for console administrators when technical preference is enabled) */}
      {isConsoleUser && technical && (
        <TechnicalDetailsSection me={me} />
      )}
    </>
  )
  if (!isConsoleUser) return <div className="space-y-6 pb-12">{body}</div>
  return (
    <PageLayout
      className="space-y-6 pb-12"
      title={t('user.me')}
      description={t('me.subtitle')}
      actions={
        <Button asChild variant="outline" size="sm">
          <Link to="/types/$type/$dn" params={{ type: 'user', dn: me.dn }}>
            {t('me.editAccount')}
            <ExternalLink className="size-3.5" aria-hidden="true" />
          </Link>
        </Button>
      }
    >
      {body}
    </PageLayout>
  )
}

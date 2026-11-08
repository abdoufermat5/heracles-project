import { Building2, KeyRound, Mail, Phone, ShieldCheck, UserCheck, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { Me } from '@/api/types'
import { OrgPath } from '@/components/patterns/OrgPath'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

export function ProfileCard({
  me,
  title,
  phone,
  mail,
  onNavigate,
}: {
  me: Me
  title?: string
  phone?: string
  mail?: string
  onNavigate: (sectionId: string) => void
}) {
  const { t } = useTranslation()
  const firstName = me.display_name ? me.display_name.split(' ')[0] : me.uid
  const initials = (me.display_name ?? me.uid ?? '?')
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()

  return (
    <div className="rounded-xl border bg-card p-5 shadow-2xs transition-all duration-150">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-4">
          <Avatar className="size-16 border-2 border-background shadow-sm">
            {me.avatar_url && <AvatarImage src={me.avatar_url} alt={me.display_name} />}
            <AvatarFallback className="bg-primary-soft text-lead font-semibold text-primary">
              {initials}
            </AvatarFallback>
          </Avatar>
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-title font-semibold tracking-tight text-foreground">
                {t('settingsUI.portal.greeting', { name: firstName })}
              </h1>
              {me.is_admin ? (
                <Badge variant="neutral">{t('me.admin', { defaultValue: 'Administrator' })}</Badge>
              ) : (
                <Badge variant="secondary" className="gap-1">
                  <UserCheck className="size-3 text-primary" aria-hidden />
                  {t('me.operator', { defaultValue: 'Employee' })}
                </Badge>
              )}
            </div>

            <p className="text-small text-muted-foreground">{t('settingsUI.portal.welcomeSubtitle')}</p>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 pt-1 text-small text-muted-foreground">
              {title && (
                <span className="font-medium text-foreground">
                  {title}
                </span>
              )}
              <span className="inline-flex items-center gap-1.5">
                <Building2 className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                <OrgPath dn={me.dn} baseDn={me.base} includeSelf={false} />
              </span>
            </div>
          </div>
        </div>

        {/* Contact info badges */}
        <div className="flex flex-col gap-1.5 text-caption text-muted-foreground sm:text-right">
          <div className="inline-flex items-center gap-1.5 sm:justify-end">
            <Mail className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <span className="font-medium text-foreground">{mail || `${me.uid}@example.com`}</span>
          </div>
          {phone && (
            <div className="inline-flex items-center gap-1.5 sm:justify-end">
              <Phone className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span>{phone}</span>
            </div>
          )}
        </div>
      </div>

      {/* Quick jump navigation */}
      <div className="mt-5 flex flex-wrap items-center gap-2 border-t pt-4">
        <span className="text-caption font-medium text-muted-foreground mr-1">
          {t('settingsUI.portal.quickLinks')}:
        </span>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-small gap-1.5"
          onClick={() => onNavigate('portal-profile')}
        >
          {t('settingsUI.portal.profileTitle')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-small gap-1.5"
          onClick={() => onNavigate('portal-password')}
        >
          <KeyRound className="size-3.5" aria-hidden />
          {t('settingsUI.portal.changePassword')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-small gap-1.5"
          onClick={() => onNavigate('portal-security')}
        >
          <ShieldCheck className="size-3.5" aria-hidden />
          {t('settingsUI.portal.protectAccount')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-small gap-1.5"
          onClick={() => onNavigate('portal-groups')}
        >
          <Users className="size-3.5" aria-hidden />
          {t('settingsUI.portal.myGroups')}
        </Button>
      </div>
    </div>
  )
}

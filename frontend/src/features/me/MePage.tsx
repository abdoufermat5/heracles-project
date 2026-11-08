import { Link, useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import {
  Check,
  Copy,
  ExternalLink,
  LogOut,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMe } from '@/api/hooks'
import { api } from '@/api/endpoints'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { SecurityKeysPanel } from './SecurityKeysPanel'
import { TwoFactorPanel } from './TwoFactorPanel'

const PANEL_HEADER = 'flex h-10 flex-row items-center justify-between border-b px-4 py-0'

export function MePage() {
  const { t, i18n } = useTranslation()
  const { data: me, isPending } = useMe()
  const { theme, setTheme } = useTheme()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [copied, setCopied] = useState(false)

  const copyDn = () => {
    if (!me?.dn) return
    void navigator.clipboard.writeText(me.dn)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const logout = async () => {
    try {
      await api.logout()
    } finally {
      qc.clear()
      void navigate({ to: '/login' })
    }
  }

  if (isPending) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label={t('common.loading')}>
        <Skeleton className="h-10 w-48" />
        <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      </div>
    )
  }

  if (!me) return null

  const initials = (me.display_name ?? me.uid ?? '?')
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()

  const currentLang = i18n.language.startsWith('fr') ? 'fr' : 'en'

  const permissions = [
    t('me.permBrowse'),
    t('me.permAttributes'),
    ...(me.is_admin ? [t('me.permModify'), t('me.permLocks'), t('me.permScope')] : []),
  ]

  return (
    <div className="space-y-4">
      <PageHeader
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
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        {/* Identity */}
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <Avatar size="lg" className="size-10">
                {me.avatar_url && <AvatarImage src={me.avatar_url} alt="" />}
                <AvatarFallback className="bg-muted text-body font-semibold text-muted-foreground">
                  {initials}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-lead font-semibold tracking-tight text-foreground">
                    {me.display_name}
                  </span>
                  <Badge variant="neutral" className="shrink-0">
                    {me.is_admin ? t('me.admin') : t('me.operator')}
                  </Badge>
                </div>
                <p className="truncate font-mono text-xs text-muted-foreground">{me.uid}</p>
              </div>
            </div>

            <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 border-t pt-4 text-body">
              <dt className="label-caps pt-0.5">{t('me.login')}</dt>
              <dd className="truncate font-mono text-foreground">{me.uid}</dd>

              <dt className="label-caps pt-0.5">{t('me.directory')}</dt>
              <dd className="truncate font-mono text-foreground">{me.directory}</dd>

              <dt className="label-caps pt-0.5">{t('me.base')}</dt>
              <dd className="break-all font-dn text-foreground">{me.base}</dd>

              <dt className="label-caps pt-0.5">{t('me.dn')}</dt>
              <dd className="flex min-w-0 items-start gap-1">
                <span className="min-w-0 flex-1 break-all font-dn text-foreground">{me.dn}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  onClick={copyDn}
                  aria-label={t('me.copyDn')}
                  title={copied ? t('me.dnCopied') : t('me.copyDn')}
                  className={cn('shrink-0', copied && 'text-success')}
                >
                  {copied ? (
                    <Check className="text-success" aria-hidden="true" />
                  ) : (
                    <Copy aria-hidden="true" />
                  )}
                </Button>
              </dd>
            </dl>
          </CardContent>
        </Card>

        {/* Permissions */}
        <Card className="overflow-hidden">
          <CardHeader className={PANEL_HEADER}>
            <CardTitle className="text-body font-semibold">{t('me.rights')}</CardTitle>
            <span className="truncate text-xs text-muted-foreground">
              {me.is_admin ? t('me.rightsAdmin') : t('me.rightsStandard')}
            </span>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y text-body">
              {permissions.map((permission) => (
                <li key={permission} className="flex items-start gap-2 px-4 py-2.5">
                  <Check className="mt-0.5 size-3.5 shrink-0 text-success" aria-hidden="true" />
                  <span className="text-foreground">{permission}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        {/* Preferences */}
        <Card className="overflow-hidden">
          <CardHeader className={PANEL_HEADER}>
            <CardTitle className="text-body font-semibold">{t('me.preferences')}</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y">
              <div className="flex items-center justify-between gap-4 px-4 py-2.5">
                <span className="text-body text-foreground">{t('user.theme')}</span>
                <ToggleGroup
                  type="single"
                  size="sm"
                  value={theme}
                  onValueChange={(value) => {
                    if (value === 'system' || value === 'light' || value === 'dark') {
                      setTheme(value)
                    }
                  }}
                  aria-label={t('user.theme')}
                >
                  <ToggleGroupItem value="system" aria-label={t('user.themeSystem')}>
                    {t('user.themeSystem')}
                  </ToggleGroupItem>
                  <ToggleGroupItem value="light" aria-label={t('user.themeLight')}>
                    {t('user.themeLight')}
                  </ToggleGroupItem>
                  <ToggleGroupItem value="dark" aria-label={t('user.themeDark')}>
                    {t('user.themeDark')}
                  </ToggleGroupItem>
                </ToggleGroup>
              </div>

              <div className="flex items-center justify-between gap-4 px-4 py-2.5">
                <span className="text-body text-foreground">{t('user.language')}</span>
                <ToggleGroup
                  type="single"
                  size="sm"
                  value={currentLang}
                  onValueChange={(value) => {
                    if (value) void i18n.changeLanguage(value)
                  }}
                  aria-label={t('user.language')}
                >
                  <ToggleGroupItem value="en" aria-label="English">
                    English
                  </ToggleGroupItem>
                  <ToggleGroupItem value="fr" aria-label="Français">
                    Français
                  </ToggleGroupItem>
                </ToggleGroup>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Session */}
        <Card>
          <CardHeader className={PANEL_HEADER}>
            <CardTitle className="text-body font-semibold">{t('me.sessionInfo')}</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 text-body">
              <dt className="label-caps pt-0.5">{t('me.activeSession')}</dt>
              <dd className="flex items-center gap-1.5 text-foreground">
                <span className="size-1.5 rounded-full bg-success" aria-hidden="true" />
                {t('me.active')}
              </dd>

              <dt className="label-caps pt-0.5">{t('me.directoryEndpoint')}</dt>
              <dd className="truncate font-mono text-foreground">{me.directory}</dd>
            </dl>

            <div className="mt-4 flex justify-end border-t pt-4">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void logout()}
                className="text-destructive hover:bg-destructive-soft hover:text-destructive"
              >
                <LogOut aria-hidden="true" />
                <span>{t('user.logout')}</span>
              </Button>
            </div>
          </CardContent>
        </Card>

        <TwoFactorPanel />
        <SecurityKeysPanel />
      </div>
    </div>
  )
}

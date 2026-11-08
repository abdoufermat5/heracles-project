import { Link, useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import {
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  Globe,
  KeyRound,
  Languages,
  LogOut,
  Monitor,
  Moon,
  Server,
  Shield,
  ShieldCheck,
  Sun,
  User,
} from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMe } from '@/api/hooks'
import { api } from '@/api/endpoints'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'

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
      <div className="max-w-4xl space-y-6" aria-busy="true" aria-label={t('common.loading')}>
        <Skeleton className="h-10 w-48" />
        <div className="grid gap-6 md:grid-cols-2">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
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

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title={t('user.me')}
        description={t('me.subtitle')}
        actions={
          <Button asChild variant="default" size="sm" className="h-8 gap-1.5 text-xs">
            <Link to="/types/$type/$dn" params={{ type: 'user', dn: me.dn }}>
              <span>{t('me.editAccount')}</span>
              <ExternalLink className="size-3.5" />
            </Link>
          </Button>
        }
      />

      <div className="grid gap-6 md:grid-cols-2">
        {/* Identity Card */}
        <Card>
          <CardHeader className="pb-4">
            <div className="flex items-start gap-3.5">
              <Avatar className="size-14 border border-border/80 shadow-xs">
                {me.avatar_url && <AvatarImage src={me.avatar_url} alt="" />}
                <AvatarFallback className="bg-primary-soft text-base font-semibold text-foreground">
                  {initials}
                </AvatarFallback>
              </Avatar>
              <div className="space-y-1 min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <CardTitle className="text-base truncate">{me.display_name}</CardTitle>
                  {me.is_admin ? (
                    <Badge variant="primary" className="text-[10px] gap-1 shrink-0">
                      <ShieldCheck className="size-3" />
                      <span>{t('me.admin')}</span>
                    </Badge>
                  ) : (
                    <Badge variant="neutral" className="text-[10px] shrink-0">
                      Operator
                    </Badge>
                  )}
                </div>
                <p className="font-mono text-xs text-muted-foreground">{me.uid}</p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 pt-0 text-xs border-t border-border/60 mt-2">
            <div className="pt-3 flex flex-col gap-1">
              <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                {t('me.login')}
              </span>
              <span className="font-mono text-foreground">{me.uid}</span>
            </div>

            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                {t('me.directory')}
              </span>
              <span className="text-foreground flex items-center gap-1.5">
                <Server className="size-3 text-muted-foreground" />
                <span>{me.directory}</span>
              </span>
            </div>

            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                {t('me.base')}
              </span>
              <span className="font-dn text-foreground break-all">{me.base}</span>
            </div>

            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                  {t('me.dn')}
                </span>
                <button
                  type="button"
                  onClick={copyDn}
                  className="text-muted-foreground hover:text-foreground text-[11px] flex items-center gap-1 transition-colors"
                  aria-label={t('me.copyDn')}
                >
                  {copied ? <Check className="size-3 text-success" /> : <Copy className="size-3" />}
                  <span>{copied ? 'Copied' : 'Copy'}</span>
                </button>
              </div>
              <span className="font-dn text-foreground break-all bg-muted/40 p-2 rounded border border-border/70 select-all">
                {me.dn}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Rights and Permissions Summary */}
        <Card className="flex flex-col justify-between">
          <div>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <Shield className="size-4 text-primary" />
                <CardTitle className="text-sm font-semibold">{t('me.rights')}</CardTitle>
              </div>
              <CardDescription className="text-xs">
                {me.is_admin ? t('me.rightsAdmin') : t('me.rightsStandard')}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2.5 text-xs">
              <div className="flex items-center gap-2 text-foreground">
                <CheckCircle2 className="size-3.5 text-success shrink-0" />
                <span>Browse and search LDAP directory tree</span>
              </div>
              <div className="flex items-center gap-2 text-foreground">
                <CheckCircle2 className="size-3.5 text-success shrink-0" />
                <span>View object attributes and schema descriptors</span>
              </div>
              {me.is_admin && (
                <>
                  <div className="flex items-center gap-2 text-foreground">
                    <CheckCircle2 className="size-3.5 text-success shrink-0" />
                    <span>Create and modify directory entries</span>
                  </div>
                  <div className="flex items-center gap-2 text-foreground">
                    <CheckCircle2 className="size-3.5 text-success shrink-0" />
                    <span>Manage account locks and password status</span>
                  </div>
                  <div className="flex items-center gap-2 text-foreground">
                    <CheckCircle2 className="size-3.5 text-success shrink-0" />
                    <span>Global department scope override</span>
                  </div>
                </>
              )}
            </CardContent>
          </div>

          <CardContent className="pt-0 border-t border-border/60">
            <div className="pt-3">
              <Button asChild variant="outline" size="sm" className="w-full text-xs h-8">
                <Link to="/types/$type/$dn" params={{ type: 'user', dn: me.dn }}>
                  <User className="size-3.5 mr-1.5" />
                  <span>{t('me.editAccount')}</span>
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Preferences Card */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold">{t('me.preferences')}</CardTitle>
            <CardDescription className="text-xs">
              Configure your visual appearance and display language
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-xs">
            {/* Theme Choice */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                {t('user.theme')}
              </label>
              <div className="grid grid-cols-3 gap-1.5 bg-muted/60 p-1 rounded-md border border-border/70">
                <button
                  type="button"
                  onClick={() => setTheme('system')}
                  className={cn(
                    'flex items-center justify-center gap-1.5 rounded py-1.5 text-xs font-medium transition-colors',
                    theme === 'system'
                      ? 'bg-card text-foreground shadow-xs font-semibold'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <Monitor className="size-3.5" />
                  <span>{t('user.themeSystem')}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setTheme('light')}
                  className={cn(
                    'flex items-center justify-center gap-1.5 rounded py-1.5 text-xs font-medium transition-colors',
                    theme === 'light'
                      ? 'bg-card text-foreground shadow-xs font-semibold'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <Sun className="size-3.5" />
                  <span>{t('user.themeLight')}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setTheme('dark')}
                  className={cn(
                    'flex items-center justify-center gap-1.5 rounded py-1.5 text-xs font-medium transition-colors',
                    theme === 'dark'
                      ? 'bg-card text-foreground shadow-xs font-semibold'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <Moon className="size-3.5" />
                  <span>{t('user.themeDark')}</span>
                </button>
              </div>
            </div>

            {/* Language Choice */}
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
                {t('user.language')}
              </label>
              <div className="grid grid-cols-2 gap-1.5 bg-muted/60 p-1 rounded-md border border-border/70">
                <button
                  type="button"
                  onClick={() => void i18n.changeLanguage('en')}
                  className={cn(
                    'flex items-center justify-center gap-1.5 rounded py-1.5 text-xs font-medium transition-colors',
                    currentLang === 'en'
                      ? 'bg-card text-foreground shadow-xs font-semibold'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <Globe className="size-3.5" />
                  <span>English</span>
                </button>
                <button
                  type="button"
                  onClick={() => void i18n.changeLanguage('fr')}
                  className={cn(
                    'flex items-center justify-center gap-1.5 rounded py-1.5 text-xs font-medium transition-colors',
                    currentLang === 'fr'
                      ? 'bg-card text-foreground shadow-xs font-semibold'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <Languages className="size-3.5" />
                  <span>Français</span>
                </button>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Session and Security Card */}
        <Card className="flex flex-col justify-between">
          <div>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <KeyRound className="size-4 text-muted-foreground" />
                <CardTitle className="text-sm font-semibold">{t('me.sessionInfo')}</CardTitle>
              </div>
              <CardDescription className="text-xs">
                Active connection and authentication details
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-xs">
              <div className="flex items-center justify-between rounded-md border border-border/70 bg-muted/40 p-2.5">
                <span className="text-muted-foreground">{t('me.activeSession')}</span>
                <span className="flex items-center gap-1.5 text-success font-medium">
                  <span className="size-2 rounded-full bg-success" />
                  <span>Active</span>
                </span>
              </div>
              <div className="flex items-center justify-between rounded-md border border-border/70 bg-muted/40 p-2.5">
                <span className="text-muted-foreground">Directory endpoint</span>
                <span className="font-mono text-foreground">{me.directory}</span>
              </div>
            </CardContent>
          </div>

          <CardContent className="pt-0 border-t border-border/60">
            <div className="pt-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void logout()}
                className="w-full text-xs h-8 text-destructive hover:bg-destructive/10 hover:text-destructive"
              >
                <LogOut className="size-3.5 mr-1.5" />
                <span>{t('user.logout')}</span>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

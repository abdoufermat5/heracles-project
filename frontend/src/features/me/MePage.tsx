import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { useMe } from '@/api/hooks'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export function MePage() {
  const { t } = useTranslation()
  const { data: me } = useMe()
  if (!me) return null
  const rows: [string, React.ReactNode][] = [
    [t('me.login'), me.uid],
    [t('me.directory'), me.directory],
    [t('me.base'), <span key="b" className="font-dn">{me.base}</span>],
    [t('me.dn'), <span key="d" className="font-dn break-all">{me.dn}</span>],
  ]
  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-xl font-semibold tracking-tight">{t('user.me')}</h1>
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>{me.display_name}</CardTitle>
          {me.is_admin && <Badge>{t('me.admin')}</Badge>}
        </CardHeader>
        <CardContent className="space-y-4">
          <dl className="grid gap-3 sm:grid-cols-[8rem_1fr]">
            {rows.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground">{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
          <Button asChild variant="outline">
            <Link to="/types/$type/$dn" params={{ type: 'user', dn: me.dn }}>
              {t('me.editAccount')}
            </Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

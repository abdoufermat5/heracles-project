import { AlertTriangle, Layers, Puzzle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ErrorState } from '@/components/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import { usePlugins } from './hooks'

export function PluginsPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = usePlugins()

  return (
    <div className="space-y-4">
      <PageHeader title={t('plugins.title')} description={t('plugins.description')} />
      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : data.length === 0 ? (
        <EmptyState
          icon={<Puzzle className="size-6 text-muted-foreground" aria-hidden />}
          title={t('plugins.none')}
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((p) => (
            <Card
              key={p.name}
              data-plugin={p.name}
              className="flex flex-col justify-between border transition-all duration-150 hover:shadow-2xs"
            >
              <div>
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Puzzle className="size-4 text-primary" aria-hidden />
                        <h3 className="text-body font-semibold tracking-tight text-foreground">
                          {p.name}
                        </h3>
                      </div>
                      <p className="font-mono text-xs tabular-nums text-muted-foreground">
                        {p.version}
                      </p>
                    </div>
                    {p.enabled ? (
                      <Badge variant="success">{t('plugins.enabled')}</Badge>
                    ) : (
                      <Badge variant="warning">{t('plugins.disabled')}</Badge>
                    )}
                  </div>
                </CardHeader>

                <CardContent className="space-y-3 pt-0">
                  {!p.enabled && p.missing_object_classes.length > 0 && (
                    <div className="flex items-start gap-2 rounded-sm border border-warning/30 bg-warning-soft p-2.5 text-caption text-warning">
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                      <div className="space-y-0.5">
                        <span className="font-medium">{t('plugins.missing')}</span>
                        <p className="font-mono text-micro break-all">
                          {p.missing_object_classes.join(', ')}
                        </p>
                      </div>
                    </div>
                  )}

                  <div className="space-y-2 border-t pt-3">
                    <span className="text-caption font-medium text-muted-foreground">
                      {t('settingsUI.plugins.addsTitle')}
                    </span>

                    {/* Types added */}
                    {p.types.length > 0 && (
                      <div className="space-y-1">
                        <span className="text-micro uppercase tracking-wide text-muted-foreground">
                          {t('plugins.types')}:
                        </span>
                        <div className="flex flex-wrap gap-1">
                          {p.types.map((ty) => (
                            <Badge key={ty.name} variant="secondary" title={ty.category}>
                              {ty.label}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Tabs added */}
                    {p.tabs.length > 0 && (
                      <div className="space-y-1">
                        <span className="text-micro uppercase tracking-wide text-muted-foreground">
                          {t('plugins.tabs')}:
                        </span>
                        <div className="flex flex-wrap gap-1">
                          {p.tabs.map((tab) => (
                            <Badge key={`${tab.type}/${tab.name}`} variant="outline">
                              <Layers className="size-3 mr-1 opacity-70" aria-hidden />
                              {tab.label}
                              <span className="ml-1 opacity-60">({tab.type})</span>
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}

                    {p.types.length === 0 && p.tabs.length === 0 && (
                      <p className="text-caption text-muted-foreground">
                        {t('settingsUI.plugins.addsNothing')}
                      </p>
                    )}
                  </div>
                </CardContent>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

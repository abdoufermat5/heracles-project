import { AlertTriangle, Layers, Puzzle } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import type { TFunction } from 'i18next'
import { Button } from '@/components/ui/button'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { ErrorState } from '@/components/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { tabLabel, typeLabel } from '@/lib/labels'
import { EmptyState } from '@/components/ui/empty-state'
import { PageLayout } from '@/components/patterns'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useCapabilities, usePlugins, useTogglePlugin } from './hooks'
import type { PluginInfo } from './types'

type Group = 'enabled' | 'available' | 'unavailable'

function groupOf(p: PluginInfo): Group {
  if (!p.available) return 'unavailable'
  return p.enabled ? 'enabled' : 'available'
}

const GROUPS: { id: Group; titleKey: string }[] = [
  { id: 'enabled', titleKey: 'plugins.groupEnabled' },
  { id: 'available', titleKey: 'plugins.groupAvailable' },
  { id: 'unavailable', titleKey: 'plugins.groupUnavailable' },
]

/** Human name of a plugin by its id; an unknown (third-party) plugin keeps its id. */
function pluginLabel(t: TFunction, name: string): string {
  return t(`plugins.names.${name}`, { defaultValue: name })
}

function PluginCard({
  p,
  canWrite,
  onToggle,
}: {
  p: PluginInfo
  canWrite: boolean
  onToggle: (enabled: boolean) => void
}) {
  const { t } = useTranslation()
  const label = pluginLabel(t, p.name)
  // why the switch cannot be used; shown as its tooltip
  const blocked = !p.available
    ? t('plugins.toggleUnavailable')
    : p.locked && p.enabled
      ? t('plugins.toggleLocked')
      : !canWrite
        ? t('plugins.toggleReadOnly')
        : null
  const toggle = (
    <Switch
      size="sm"
      checked={p.enabled}
      disabled={blocked !== null}
      onCheckedChange={onToggle}
      aria-label={t('plugins.toggle', { name: label })}
    />
  )

  return (
    <Card
      data-plugin={p.name}
      className="flex flex-col justify-between border transition-all duration-150 hover:shadow-2xs"
    >
      <div>
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-2">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Puzzle className="size-4 text-primary" aria-hidden />
                <h3 className="text-body font-semibold tracking-tight text-foreground">{label}</h3>
              </div>
              <p className="font-mono text-xs tabular-nums text-muted-foreground">
                <span>{p.name}</span> · <span>{p.version}</span>
              </p>
            </div>
            <div className="flex items-center gap-2">
              {!p.available ? (
                <Badge variant="warning">{t('plugins.unavailable')}</Badge>
              ) : p.enabled ? (
                <Badge variant="success">{t('plugins.enabled')}</Badge>
              ) : (
                <Badge variant="secondary">{t('plugins.disabled')}</Badge>
              )}
              {blocked ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span tabIndex={0}>{toggle}</span>
                  </TooltipTrigger>
                  <TooltipContent>{blocked}</TooltipContent>
                </Tooltip>
              ) : (
                toggle
              )}
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-3 pt-0">
          {p.locked && p.enabled && (
            <p className="text-caption text-muted-foreground">{t('plugins.toggleLocked')}</p>
          )}
          {!p.available && p.missing_object_classes.length > 0 && (
            <div className="flex items-start gap-2 rounded-sm border border-warning/30 bg-warning-soft p-2.5 text-caption text-warning">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <div className="space-y-0.5">
                <span className="font-medium">{t('plugins.missing')}</span>
                <p className="font-mono text-micro break-all">{p.missing_object_classes.join(', ')}</p>
              </div>
            </div>
          )}

          <div className="space-y-2 border-t pt-3">
            <span className="text-caption font-medium text-muted-foreground">{t('settingsUI.plugins.addsTitle')}</span>

            {p.types.length > 0 && (
              <div className="space-y-1">
                <span className="text-micro uppercase tracking-wide text-muted-foreground">{t('plugins.types')}:</span>
                <div className="flex flex-wrap gap-1">
                  {p.types.map((ty) => (
                    <Badge key={ty.name} variant="secondary" title={ty.category}>
                      {typeLabel(t, ty)}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {p.tabs.length > 0 && (
              <div className="space-y-1">
                <span className="text-micro uppercase tracking-wide text-muted-foreground">{t('plugins.tabs')}:</span>
                <div className="flex flex-wrap gap-1">
                  {p.tabs.map((tab) => (
                    <Badge key={`${tab.type}/${tab.name}`} variant="outline">
                      <Layers className="size-3 mr-1 opacity-70" aria-hidden />
                      {tabLabel(t, tab)}
                      <span className="ml-1 opacity-60">
                        ({typeLabel(t, { name: tab.type, label: tab.type })})
                      </span>
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {p.types.length === 0 && p.tabs.length === 0 && (
              <p className="text-caption text-muted-foreground">{t('settingsUI.plugins.addsNothing')}</p>
            )}
          </div>
        </CardContent>
      </div>
    </Card>
  )
}

export function PluginsPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = usePlugins()
  const caps = useCapabilities()
  const toggle = useTogglePlugin()

  const change = (p: PluginInfo, enabled: boolean) =>
    toggle.mutate(
      { name: p.name, enabled },
      {
        onSuccess: (res) => {
          toast.success(
            t(enabled ? 'plugins.turnedOn' : 'plugins.turnedOff', {
              name: pluginLabel(t, p.name),
            }),
          )
          if (res.restart_required) toast.info(t('plugins.restartRequired'))
        },
        onError: (e) => toast.error(isApiError(e) ? e.message : t('plugins.toggleFailed', { name: pluginLabel(t, p.name) })),
      },
    )

  return (
    <PageLayout title={t('plugins.title')} description={t('plugins.description')}>
      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : data.length === 0 ? (
        <EmptyState icon={<Puzzle className="size-6 text-muted-foreground" aria-hidden />} title={t('plugins.none')}
          action={
            <Button asChild variant="outline" size="sm">
              <Link to="/admin/health">{t('onboarding.next.health')}</Link>
            </Button>
          }
        />
      ) : (
        GROUPS.map((g) => {
          const items = data.filter((p) => groupOf(p) === g.id)
          if (items.length === 0) return null
          return (
            <section key={g.id} data-group={g.id} className="space-y-3">
              <h2 className="text-body font-semibold text-foreground">
                {t(g.titleKey)} <span className="text-muted-foreground">({items.length})</span>
              </h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((p) => (
                  <PluginCard
                    key={p.name}
                    p={p}
                    canWrite={caps.data?.config_write ?? false}
                    onToggle={(on) => change(p, on)}
                  />
                ))}
              </div>
            </section>
          )
        })
      )}
    </PageLayout>
  )
}

import { Shield, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/endpoints'
import { SectionCard } from '@/components/patterns/SectionCard'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'

export function GroupsSection() {
  const { t } = useTranslation()
  const { data, isPending, isError } = useQuery({
    queryKey: ['me', 'groups'],
    queryFn: api.myGroups,
    staleTime: 60_000,
  })
  const groupRefs = data ?? []

  return (
    <SectionCard
      id="portal-groups"
      title={
        <div className="flex items-center gap-2">
          <span>{t('settingsUI.portal.myGroups')}</span>
          <Badge variant="neutral">
            {t('settingsUI.portal.groupsCount', { count: groupRefs.length })}
          </Badge>
        </div>
      }
      description={t('settingsUI.portal.myGroupsSubtitle')}
    >
      {isPending ? (
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : isError ? (
        <p className="text-small text-muted-foreground">{t('settingsUI.portal.groupsUnavailable')}</p>
      ) : groupRefs.length === 0 ? (
        <EmptyState
          icon={<Users className="size-6 text-muted-foreground" aria-hidden />}
          title={t('settingsUI.portal.noGroups')}
        />
      ) : (
        <div className="grid gap-2.5 sm:grid-cols-2">
          {groupRefs.map((group) => (
            <div
              key={group.dn}
              className="flex items-center justify-between gap-3 rounded-lg border bg-card p-3 shadow-2xs transition-colors hover:bg-accent/40"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                  <Users className="size-4" aria-hidden />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-body font-medium text-foreground">
                    {group.name}
                  </p>
                  <p className="text-micro text-muted-foreground uppercase tracking-wide">
                    {t('settingsUI.portal.groupMember')}
                  </p>
                </div>
              </div>
              <Badge variant="secondary" className="shrink-0 gap-1 text-micro">
                <Shield className="size-3" aria-hidden />
                {t('settingsUI.portal.memberBadge')}
              </Badge>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  )
}

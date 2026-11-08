import { Lock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { useCapabilities } from './hooks'
import type { Capabilities } from './types'

export type AdminCapability = Exclude<keyof Capabilities, 'is_admin' | 'config_write'>

/** Renders its children only when the user holds the rights for this administration screen. */
export function AdminGate({
  capability,
  children,
}: {
  capability: AdminCapability
  children: React.ReactNode
}) {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = useCapabilities()
  if (isPending) return <Skeleton className="h-40 w-full" />
  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />
  if (!data[capability]) {
    return (
      <EmptyState
        icon={<Lock />}
        title={t('admin.noAccess')}
        description={t('admin.noAccessHelp')}
        className="mx-auto max-w-md"
      />
    )
  }
  return <>{children}</>
}

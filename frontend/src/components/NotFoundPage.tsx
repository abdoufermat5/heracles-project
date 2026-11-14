import { Compass } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ErrorNavigation } from '@/components/ErrorState'
import { EmptyState } from '@/components/ui/empty-state'

/** The page an address that matches no route (or a missing object) shows. */
export function NotFoundPage() {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-[60vh] items-center justify-center p-6">
      <EmptyState
        icon={<Compass className="size-6 text-muted-foreground" aria-hidden />}
        title={t('common.notFound')}
        description={t('common.notFoundHelp')}
        action={
          <div className="flex flex-wrap justify-center gap-2">
            <ErrorNavigation />
          </div>
        }
        className="max-w-md w-full py-14"
      />
    </div>
  )
}

import { Puzzle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ErrorState } from '@/components/ErrorState'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { PageHeader } from '@/components/ui/page-header'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { usePlugins } from './hooks'

export function PluginsPage() {
  const { t } = useTranslation()
  const { data, isPending, isError, error, refetch } = usePlugins()

  return (
    <div>
      <PageHeader title={t('plugins.title')} description={t('plugins.description')} />
      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : data.length === 0 ? (
        <EmptyState icon={<Puzzle />} title={t('plugins.none')} />
      ) : (
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('plugins.name')}</TableHead>
                <TableHead>{t('plugins.version')}</TableHead>
                <TableHead>{t('plugins.status')}</TableHead>
                <TableHead>{t('plugins.types')}</TableHead>
                <TableHead>{t('plugins.tabs')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((p) => (
                <TableRow key={p.name} data-plugin={p.name}>
                  <TableCell className="align-top font-medium">{p.name}</TableCell>
                  <TableCell className="align-top font-mono text-xs tabular-nums">{p.version}</TableCell>
                  <TableCell className="align-top">
                    {p.enabled ? (
                      <Badge variant="success">{t('plugins.enabled')}</Badge>
                    ) : (
                      <div className="space-y-1">
                        <Badge variant="warning">{t('plugins.disabled')}</Badge>
                        <p className="text-caption text-muted-foreground">
                          {t('plugins.missing')}{' '}
                          <span className="font-mono">{p.missing_object_classes.join(', ')}</span>
                        </p>
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="align-top">
                    <div className="flex flex-wrap gap-1">
                      {p.types.length === 0 && <span className="text-muted-foreground">—</span>}
                      {p.types.map((ty) => (
                        <Badge key={ty.name} variant="secondary" title={ty.category}>
                          {ty.label}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="align-top">
                    <div className="flex flex-wrap gap-1">
                      {p.tabs.length === 0 && <span className="text-muted-foreground">—</span>}
                      {p.tabs.map((tab) => (
                        <Badge key={`${tab.type}/${tab.name}`} variant="outline">
                          {tab.label}
                          <span className="ml-1 opacity-60">{tab.type}</span>
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

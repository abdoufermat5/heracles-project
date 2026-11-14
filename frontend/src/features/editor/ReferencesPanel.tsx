import { Link } from '@tanstack/react-router'
import { Link2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useTypes } from '@/api/hooks'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ErrorState } from '@/components/ErrorState'
import { typeLabel } from '@/lib/labels'
import { useReferences } from './api'

/** Read-only list of the objects that point to this one. */
export function ReferencesPanel({ type, dn }: { type: string; dn: string }) {
  const { t } = useTranslation()
  const refs = useReferences(type, dn)
  const types = useTypes()
  const labelOfType = (name: string) => {
    const found = types.data?.find((x) => x.name === name)
    return found ? typeLabel(t, found) : name
  }

  return (
    <section aria-labelledby="refs-title" className="rounded-md border bg-card">
      <div className="border-b px-4 py-3">
        <h2 id="refs-title" className="text-body font-semibold text-foreground">
          {t('references.title')}
        </h2>
        <p className="text-xs text-muted-foreground">{t('references.help')}</p>
      </div>

      {refs.isError ? (
        <div className="p-4">
          <ErrorState error={refs.error} onRetry={() => void refs.refetch()} />
        </div>
      ) : !refs.data ? (
        <div className="space-y-2 p-4" aria-busy="true" aria-label={t('common.loading')}>
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-5 w-1/2" />
        </div>
      ) : refs.data.length === 0 ? (
        <div className="p-4">
          <EmptyState
            icon={<Link2 aria-hidden />}
            title={t('references.empty')}
            className="border-0 py-8"
          />
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('references.columnObject')}</TableHead>
              <TableHead>{t('references.columnType')}</TableHead>
              <TableHead>{t('references.columnAttribute')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {refs.data.map((r) => (
              <TableRow key={`${r.dn}|${r.attribute}`}>
                <TableCell className="min-w-0">
                  <Link
                    to="/types/$type/$dn"
                    params={{ type: r.type, dn: r.dn }}
                    className="font-medium text-primary underline-offset-4 hover:underline"
                    title={r.dn}
                  >
                    {r.label}
                  </Link>
                </TableCell>
                <TableCell>
                  <Badge variant="neutral">
                    {labelOfType(r.type)}
                  </Badge>
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {t(`references.attribute_${r.attribute}`, { defaultValue: r.attribute })}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  )
}

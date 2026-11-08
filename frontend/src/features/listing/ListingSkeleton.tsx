import { useTranslation } from 'react-i18next'
import type { ColumnDescriptor } from '@/api/types'
import { Skeleton } from '@/components/ui/skeleton'
import type { Density } from './types'

interface ListingSkeletonProps {
  columns: ColumnDescriptor[]
  density: Density
  isPersonType?: boolean
}

export function ListingSkeleton({
  columns,
  density,
  isPersonType = false,
}: ListingSkeletonProps) {
  const { t } = useTranslation()
  const rowCount = 8
  const rowHeight = density === 'compact' ? 'h-[30px]' : 'h-9'

  const colWidths = ['w-28', 'w-36', 'w-24', 'w-40', 'w-20']

  return (
    <div
      aria-busy="true"
      aria-label={t('common.loading')}
      className="overflow-hidden rounded-b-md border bg-card"
    >
      <div className="overflow-x-auto">
        <table className="w-full text-body">
          <thead className="border-b bg-muted/50">
            <tr>
              <th className="h-8 w-10 px-3">
                <Skeleton className="mx-auto size-3.5 rounded-sm" />
              </th>
              {columns.map((col) => (
                <th key={col.key} className="h-8 px-3 text-left">
                  <Skeleton className="h-3 w-20" />
                </th>
              ))}
              <th className="h-8 w-20 px-3 text-right">
                <Skeleton className="ml-auto h-3 w-10" />
              </th>
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rowCount }, (_, i) => (
              <tr key={i} className={`${rowHeight} border-b last:border-b-0`}>
                <td className="w-10 px-3">
                  <Skeleton className="mx-auto size-3.5 rounded-sm" />
                </td>
                {columns.map((col, cIdx) => (
                  <td key={col.key} className="px-3">
                    {cIdx === 0 && isPersonType ? (
                      <Skeleton className="h-3.5 w-36" />
                    ) : (
                      <Skeleton
                        className={`h-3.5 ${colWidths[cIdx % colWidths.length]}`}
                      />
                    )}
                  </td>
                ))}
                <td className="w-20 px-3 text-right">
                  <Skeleton className="ml-auto h-5 w-12 rounded-sm" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

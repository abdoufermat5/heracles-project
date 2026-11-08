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
  const rowHeight = density === 'compact' ? 'h-8' : 'h-10'

  const colWidths = ['w-28', 'w-36', 'w-24', 'w-40', 'w-20']

  return (
    <div
      aria-busy="true"
      aria-label={t('common.loading')}
      className="bg-card overflow-hidden rounded-xl border border-border shadow-xs"
    >
      <div className="overflow-x-auto">
        <table className="w-full caption-bottom text-sm">
          <thead className="bg-muted/40 border-b border-border">
            <tr>
              <th className="w-10 px-3 py-2">
                <Skeleton className="size-4 rounded" />
              </th>
              {columns.map((col) => (
                <th key={col.key} className="px-3 py-2 text-left">
                  <Skeleton className="h-4 w-20" />
                </th>
              ))}
              <th className="w-24 px-3 py-2 text-right">
                <Skeleton className="ml-auto h-4 w-12" />
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {Array.from({ length: rowCount }, (_, i) => (
              <tr key={i} className={rowHeight}>
                <td className="w-10 px-3">
                  <Skeleton className="size-4 rounded" />
                </td>
                {columns.map((col, cIdx) => (
                  <td key={col.key} className="px-3">
                    {cIdx === 0 && isPersonType ? (
                      <div className="flex items-center gap-2.5">
                        <Skeleton className="size-7 rounded-full shrink-0" />
                        <Skeleton
                          className={`h-4 ${colWidths[cIdx % colWidths.length]}`}
                        />
                      </div>
                    ) : (
                      <Skeleton
                        className={`h-4 ${colWidths[cIdx % colWidths.length]}`}
                      />
                    )}
                  </td>
                ))}
                <td className="w-24 px-3 text-right">
                  <Skeleton className="ml-auto h-6 w-14 rounded" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

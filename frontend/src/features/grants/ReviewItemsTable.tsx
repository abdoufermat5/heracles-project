import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { rdnValue } from '@/lib/objects'
import { accessApi } from './api'
import type { ReviewDecision, ReviewItem } from './types'

/** Review items with keep / revoke buttons; `showDn` adds the DNs (console). */
export function ReviewItemsTable({
  campaignId,
  items,
  showDn = true,
  showReviewer = false,
}: {
  campaignId: string
  items: ReviewItem[]
  showDn?: boolean
  showReviewer?: boolean
}) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const decide = useMutation({
    mutationFn: ({ item, decision }: { item: ReviewItem; decision: ReviewDecision }) =>
      accessApi.decideItem(campaignId, item.id, decision, ''),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['access'] }),
    onError: (e) => toast.error(isApiError(e) ? e.message : t('grants.reviews.decideFailed')),
  })

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('grants.reviews.member')}</TableHead>
          <TableHead>{t('grants.reviews.access')}</TableHead>
          {showReviewer ? <TableHead className="hidden md:table-cell">{t('grants.reviews.reviewer')}</TableHead> : null}
          <TableHead>{t('grants.reviews.decision')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <TableRow key={item.id} data-testid="review-item">
            <TableCell>
              <span className="block font-medium text-foreground">{rdnValue(item.member)}</span>
              {showDn ? <span className="block font-mono text-caption text-muted-foreground">{item.member}</span> : null}
            </TableCell>
            <TableCell>
              <span className="block text-foreground">{item.holder.label}</span>
              {showDn ? <span className="block font-mono text-caption text-muted-foreground">{item.holder.dn}</span> : null}
            </TableCell>
            {showReviewer ? (
              <TableCell className="hidden text-small text-muted-foreground md:table-cell">
                {item.reviewer ? rdnValue(item.reviewer) : t('grants.reviews.managers')}
              </TableCell>
            ) : null}
            <TableCell>
              {item.outcome ? (
                <span className="text-small text-foreground">{t(`grants.reviews.outcome.${item.outcome}`, { defaultValue: item.outcome })}</span>
              ) : item.can_decide ? (
                <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('grants.reviews.decideFor', { member: rdnValue(item.member) })}>
                  <Button
                    type="button"
                    size="sm"
                    variant={item.decision === 'keep' ? 'default' : 'outline'}
                    aria-pressed={item.decision === 'keep'}
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ item, decision: 'keep' })}
                  >
                    {t('grants.reviews.keep')}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={item.decision === 'revoke' ? 'destructive' : 'outline'}
                    aria-pressed={item.decision === 'revoke'}
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ item, decision: 'revoke' })}
                  >
                    {t('grants.reviews.revoke')}
                  </Button>
                </div>
              ) : (
                <span className="text-small text-muted-foreground">
                  {item.decision ? t(`grants.reviews.${item.decision}`) : t('grants.reviews.undecided')}
                </span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

import { Link } from '@tanstack/react-router'
import { FileText, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
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
import { useTemplateMutations, useTemplates, type TemplateInfo } from '@/features/editor/api'

interface Props {
  type: string
  typeLabel: string
  canCreate: boolean
}

/** Templates of one type: list, create, edit and delete (the editor is a separate page). */
export function TemplatesView({ type, typeLabel, canCreate }: Props) {
  const { t } = useTranslation()
  const templates = useTemplates(type)
  const { remove } = useTemplateMutations(type)
  const [target, setTarget] = useState<TemplateInfo | null>(null)

  const doDelete = async () => {
    if (!target) return
    try {
      await remove.mutateAsync(target.dn)
      toast.success(t('templates.deleted'))
    } catch (e) {
      toast.error(isApiError(e) ? e.message : t('common.error'))
    } finally {
      setTarget(null)
    }
  }

  const newButton = canCreate ? (
    <Button asChild size="sm">
      <Link to="/types/$type/templates/new" params={{ type }}>
        <Plus aria-hidden />
        {t('templates.new')}
      </Link>
    </Button>
  ) : null

  return (
    <section aria-labelledby="templates-title" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 id="templates-title" className="text-[13px] font-semibold text-foreground">
            {t('templates.title')} — {typeLabel}
          </h2>
          <p className="text-xs text-muted-foreground">{t('templates.emptyHelp')}</p>
        </div>
        {newButton}
      </div>

      {templates.isError ? (
        <ErrorState error={templates.error} onRetry={() => void templates.refetch()} />
      ) : !templates.data ? (
        <div className="space-y-2" aria-busy="true" aria-label={t('common.loading')}>
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      ) : templates.data.length === 0 ? (
        <EmptyState
          icon={<FileText aria-hidden />}
          title={t('templates.empty')}
          description={t('templates.emptyHelp')}
          action={newButton}
        />
      ) : (
        <div className="rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('templates.columnName')}</TableHead>
                <TableHead>{t('templates.columnDepartment')}</TableHead>
                <TableHead className="w-0">
                  <span className="sr-only">{t('listing.actions')}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {templates.data.map((tpl) => (
                <TableRow key={tpl.dn}>
                  <TableCell className="font-medium">
                    <Link
                      to="/types/$type/templates/$dn"
                      params={{ type, dn: tpl.dn }}
                      className="text-primary underline-offset-4 hover:underline"
                    >
                      {tpl.name}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground" title={tpl.base}>
                    {tpl.base}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      <Button asChild variant="ghost" size="icon-sm">
                        <Link
                          to="/types/$type/templates/$dn"
                          params={{ type, dn: tpl.dn }}
                          aria-label={`${t('templates.edit')} ${tpl.name}`}
                        >
                          <Pencil aria-hidden />
                        </Link>
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        className="text-muted-foreground hover:text-destructive"
                        onClick={() => setTarget(tpl)}
                        aria-label={`${t('common.delete')} ${tpl.name}`}
                      >
                        <Trash2 aria-hidden />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <AlertDialog open={target !== null} onOpenChange={(o) => !o && setTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[15px] font-semibold">
              {t('templates.deleteTitle', { name: target?.name ?? '' })}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[13px] text-muted-foreground">
              {t('templates.deleteBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void doDelete()}>
              {t('common.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

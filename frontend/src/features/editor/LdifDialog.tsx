import { Check, Copy, FileCode2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Skeleton } from '@/components/ui/skeleton'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  ldif: string
  title: string
  /** The server text is still being fetched. */
  loading?: boolean
}

export function LdifDialog({ open, onOpenChange, ldif, title, loading = false }: Props) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const onCopy = async () => {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      await navigator.clipboard.writeText(ldif)
      setCopied(true)
      toast.success(t('editor.copied'))
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-w-2xl flex-col sm:max-h-[85vh]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lead">
            <FileCode2 className="size-4 text-muted-foreground" aria-hidden />
            {t('editor.ldifTitle')} — {title}
          </DialogTitle>
          <DialogDescription className="text-body">
            {t('editor.rawLdif')}
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="h-96 w-full rounded-sm border bg-muted/40 p-3">
          {loading ? (
            <div className="space-y-2" aria-busy="true" aria-label={t('common.loading')}>
              <Skeleton className="h-3.5 w-2/3" />
              <Skeleton className="h-3.5 w-1/2" />
              <Skeleton className="h-3.5 w-3/4" />
            </div>
          ) : (
            <pre className="font-dn text-xs leading-relaxed whitespace-pre-wrap text-foreground select-text">
              {ldif}
            </pre>
          )}
        </ScrollArea>

        <DialogFooter className="flex items-center justify-between sm:justify-between">
          <Button type="button" variant="outline" size="sm" onClick={onCopy} disabled={loading}>
            {copied ? <Check className="text-success" /> : <Copy />}
            {t('editor.copyLdif')}
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => onOpenChange(false)}
          >
            {t('common.close', 'Close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

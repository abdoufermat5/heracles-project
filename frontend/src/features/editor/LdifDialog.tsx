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

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  ldif: string
  title: string
}

export function LdifDialog({ open, onOpenChange, ldif, title }: Props) {
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
      <DialogContent className="max-w-2xl sm:max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base font-semibold">
            <FileCode2 className="size-4 text-primary" />
            {t('editor.ldifTitle')} — {title}
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            {t('editor.rawLdif')}
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="h-96 w-full rounded-md border border-border bg-muted/40 p-3">
          <pre className="font-dn text-xs text-foreground whitespace-pre-wrap select-text leading-relaxed">
            {ldif}
          </pre>
        </ScrollArea>

        <DialogFooter className="flex items-center justify-between sm:justify-between">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onCopy}
            className="h-8 gap-1.5"
          >
            {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
            {t('editor.copyLdif')}
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => onOpenChange(false)}
            className="h-8"
          >
            {t('common.close', 'Close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

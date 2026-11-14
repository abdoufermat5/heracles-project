import { Check, Copy, FileCode2, Terminal, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { shellQuote } from '@/features/listing/ldapsearch'
import { useObjectLdif } from './api'
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
  /** Object type and DN of the entry whose LDIF the server builds. */
  type: string
  dn: string
  title: string
}

/** The raw LDIF of an entry, as the server builds it; a failed request shows its reason. */
export function LdifDialog({ open, onOpenChange, type, dn, title }: Props) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const query = useObjectLdif(type, dn, open)
  const ldif = query.data ?? ''
  const loading = open && query.isPending
  const failure = query.error
  const failureText = !query.isError
    ? null
    : isApiError(failure) && (failure.status === 404 || failure.status === 501)
      ? t('editorUI.ldifUnavailable')
      : isApiError(failure) && failure.status === 403
        ? t('editorUI.ldifForbidden')
        : t('editorUI.ldifError')

  const onCopy = async () => {
    if (ldif && typeof navigator !== 'undefined' && navigator.clipboard) {
      await navigator.clipboard.writeText(ldif)
      setCopied(true)
      toast.success(t('editor.copied'))
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const onCopySearch = () => {
    void navigator.clipboard?.writeText(
      `ldapsearch -H 'ldap://HOST' -D '<BIND_DN>' -W -b ${shellQuote(dn)} -s base '(objectClass=*)'`,
    )
    toast.success(t('safety.ldapsearchCopied'))
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
          ) : failureText ? (
            <p role="alert" className="flex items-start gap-2 text-body text-destructive">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span>{failureText}</span>
            </p>
          ) : (
            <pre className="font-dn text-xs leading-relaxed whitespace-pre-wrap text-foreground select-text">
              {ldif}
            </pre>
          )}
        </ScrollArea>

        <DialogFooter className="flex items-center justify-between sm:justify-between">
          <Button type="button" variant="outline" size="sm" onClick={onCopy} disabled={loading || !ldif}>
            {copied ? <Check className="text-success" /> : <Copy />}
            {t('editor.copyLdif')}
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onCopySearch}>
            <Terminal />
            {t('safety.copyLdapsearch')}
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => onOpenChange(false)}
          >
            {t('editorUI.close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

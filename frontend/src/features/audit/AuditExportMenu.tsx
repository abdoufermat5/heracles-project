import { ChevronDown, Download } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ReauthDialog } from '@/features/me/ReauthDialog'
import { auditApi, type AuditExportFormat } from './api'
import type { AuditFilters } from './types'

/** Save a blob under a name, through a temporary link. */
function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

/** Download the filtered log for auditors; asks for the password again when the sign-in is old. */
export function AuditExportMenu({ filters }: { filters: AuditFilters }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<AuditExportFormat | null>(null)

  async function run(format: AuditExportFormat) {
    setBusy(true)
    try {
      const { blob, name } = await auditApi.export(filters, format)
      saveBlob(blob, name)
    } catch (e) {
      if (isApiError(e) && e.code === 'reauth_required') setPending(format)
      else toast.error(isApiError(e) ? e.message : t('audit.export.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" disabled={busy}>
            <Download aria-hidden />
            {t('audit.export.label')}
            <ChevronDown aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => void run('csv')}>{t('audit.export.csv')}</DropdownMenuItem>
          <DropdownMenuItem onSelect={() => void run('json')}>{t('audit.export.json')}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ReauthDialog
        open={pending !== null}
        body={t('audit.export.reauthBody')}
        onCancel={() => setPending(null)}
        onConfirmed={() => {
          const format = pending
          setPending(null)
          if (format) void run(format)
        }}
      />
    </>
  )
}

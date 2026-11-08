import { Check, Copy, Terminal } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Me } from '@/api/types'
import { FactList, SectionCard } from '@/components/patterns/SectionCard'
import { Badge } from '@/components/ui/badge'

export function TechnicalDetailsSection({ me }: { me: Me }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const copyDn = () => {
    void navigator.clipboard?.writeText(me.dn).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const permissions = [
    t('me.permBrowse', { defaultValue: 'Directory search and browse' }),
    t('me.permAttributes', { defaultValue: 'View directory entry attributes' }),
    ...(me.is_admin
      ? [
          t('me.permModify', { defaultValue: 'Create and modify directory entries' }),
          t('me.permLocks', { defaultValue: 'Lock and unlock accounts' }),
          t('me.permScope', { defaultValue: 'Manage directory subtree configurations' }),
        ]
      : []),
  ]

  return (
    <SectionCard
      id="portal-technical"
      title={
        <div className="flex items-center gap-2">
          <Terminal className="size-4 text-muted-foreground" aria-hidden />
          <span>{t('settingsUI.portal.technicalDetails')}</span>
        </div>
      }
      description={t('settingsUI.portal.technicalDetailsSubtitle')}
    >
      <FactList
        items={[
          {
            label: t('me.login', { defaultValue: 'Login attribute' }),
            value: <span className="font-mono text-xs">{me.uid}</span>,
          },
          {
            label: t('me.directory', { defaultValue: 'Directory instance' }),
            value: <span className="font-mono text-xs">{me.directory}</span>,
          },
          {
            label: t('me.base', { defaultValue: 'Base entry' }),
            value: <span className="font-mono text-xs">{me.base}</span>,
          },
          {
            label: t('me.dn', { defaultValue: 'Distinguished name (DN)' }),
            value: (
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="truncate font-mono text-xs text-muted-foreground">{me.dn}</span>
                <button
                  type="button"
                  onClick={copyDn}
                  className="shrink-0 p-1 text-muted-foreground hover:text-foreground"
                  aria-label={t('me.copyDn', { defaultValue: 'Copy DN' })}
                  title={copied ? t('me.copied', { defaultValue: 'Copied' }) : t('me.copyDn', { defaultValue: 'Copy DN' })}
                >
                  {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
                </button>
              </div>
            ),
          },
        ]}
      />

      <div className="mt-4 border-t pt-3">
        <span className="text-caption font-medium text-muted-foreground">
          {t('me.permissions', { defaultValue: 'Assigned capabilities' })}:
        </span>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {permissions.map((p) => (
            <Badge key={p} variant="secondary" className="text-micro font-normal">
              {p}
            </Badge>
          ))}
        </div>
      </div>
    </SectionCard>
  )
}

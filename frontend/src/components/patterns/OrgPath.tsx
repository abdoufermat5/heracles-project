import { Building2, Check, Copy } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { orgPath } from '@/lib/dn'
import { useTechnicalDetails } from '@/lib/preferences'
import { cn } from '@/lib/utils'

/**
 * Where an entry lives, as people say it: "Paris › Sales".
 *
 * The distinguished name stays one hover (and one click to copy) away; with
 * "technical details" on, a copy icon makes that visible at a glance.
 */
export function OrgPath({
  dn,
  baseDn,
  includeSelf = false,
  showIcon = true,
  className,
}: {
  dn: string
  baseDn?: string
  includeSelf?: boolean
  showIcon?: boolean
  className?: string
}) {
  const { t } = useTranslation()
  const technical = useTechnicalDetails()
  const [copied, setCopied] = useState(false)
  const path = orgPath(dn, baseDn, includeSelf)

  const copy = () => {
    void navigator.clipboard?.writeText(dn).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={copy}
          className={cn(
            'inline-flex min-w-0 items-center gap-1.5 text-left text-muted-foreground hover:text-foreground',
            className,
          )}
          aria-label={t('patterns.locationOf', { path: path.join(' › ') || t('patterns.topLevel') })}
        >
          {showIcon && <Building2 className="size-3.5 shrink-0" aria-hidden />}
          <span className="truncate">
            {path.length > 0 ? path.join(' › ') : t('patterns.topLevel')}
          </span>
          {technical &&
            (copied ? (
              <Check className="size-3.5 shrink-0" aria-hidden />
            ) : (
              <Copy className="size-3.5 shrink-0 opacity-60" aria-hidden />
            ))}
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-md">
        <span className="font-dn break-all">{dn}</span>
        <span className="mt-1 block opacity-70">
          {copied ? t('patterns.copied') : t('patterns.clickToCopy')}
        </span>
      </TooltipContent>
    </Tooltip>
  )
}

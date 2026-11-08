import { CircleHelp } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

/** Help popover listing the placeholder ("mask") syntax of template values. */
export function MaskHelp() {
  const { t } = useTranslation()
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          <CircleHelp aria-hidden />
          {t('templates.syntaxButton')}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[26rem] max-w-[90vw] space-y-2 text-body">
        <h2 className="text-body font-semibold text-foreground">{t('templates.syntaxTitle')}</h2>
        <p className="text-muted-foreground">{t('templates.syntaxIntro')}</p>
        <ul className="space-y-2 text-muted-foreground">
          <li>{t('templates.syntaxAttr')}</li>
          <li>{t('templates.syntaxModifiers')}</li>
          <li>{t('templates.syntaxArray')}</li>
          <li>{t('templates.syntaxString')}</li>
        </ul>
        <p className="rounded-sm border bg-muted/40 p-2 font-mono text-xs text-foreground">
          {t('templates.syntaxExample')}
        </p>
      </PopoverContent>
    </Popover>
  )
}

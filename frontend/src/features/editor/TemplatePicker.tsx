import { FileText } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useTemplates } from './api'

/** Select value standing for "no template" (an empty value is reserved by the Select). */
const NONE = '__none__'

interface Props {
  type: string
  /** DN of the chosen template, `null` for a blank object. */
  selected: string | null
  onChange: (templateDn: string | null) => void
  disabled?: boolean
}

/** Lists the templates of a type in create mode; renders nothing when there are none. */
export function TemplatePicker({ type, selected, onChange, disabled }: Props) {
  const { t } = useTranslation()
  const templates = useTemplates(type)
  const items = templates.data ?? []

  if (items.length === 0) return null

  return (
    <div className="flex items-center gap-3 rounded-md border bg-card p-3">
      <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <label htmlFor="template-picker" className="block text-body font-medium text-foreground">
          {t('templates.picker')}
        </label>
        <p className="text-xs text-muted-foreground">{t('templates.pickerHelp')}</p>
      </div>
      <div className="w-64">
        <Select
          value={selected ?? NONE}
          onValueChange={(v) => onChange(v === NONE ? null : v)}
          disabled={disabled}
        >
          <SelectTrigger id="template-picker" className="h-8 text-body">
            <SelectValue placeholder={t('templates.pickerPlaceholder')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>{t('templates.pickerNone')}</SelectItem>
            {items.map((tpl) => (
              <SelectItem key={tpl.dn} value={tpl.dn}>
                {tpl.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}

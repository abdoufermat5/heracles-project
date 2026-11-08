import { FileText } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

interface Props {
  templates?: Array<{ id: string; label: string }>
  selected: string | null
  onChange: (templateId: string | null) => void
  disabled?: boolean
}

export function TemplatePicker({
  templates = [],
  selected,
  onChange,
  disabled,
}: Props) {
  const { t } = useTranslation()

  if (templates.length === 0) return null

  return (
    <div className="flex items-center gap-3 rounded-md border bg-card p-3">
      <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1">
        <label
          htmlFor="template-picker"
          className="block text-[13px] font-medium text-foreground"
        >
          {t('editor.template')}
        </label>
        <p className="text-[12px] text-muted-foreground">{t('editor.selectTemplate')}</p>
      </div>
      <div className="w-56">
        <Select
          value={selected ?? ''}
          onValueChange={(v) => onChange(v === '' ? null : v)}
          disabled={disabled}
        >
          <SelectTrigger id="template-picker" className="h-8 text-[13px]">
            <SelectValue placeholder={t('editor.selectTemplate')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">{t('editor.noTemplate')}</SelectItem>
            {templates.map((tpl) => (
              <SelectItem key={tpl.id} value={tpl.id}>
                {tpl.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}

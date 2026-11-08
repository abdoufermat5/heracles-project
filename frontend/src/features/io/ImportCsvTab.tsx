import { CheckCircle2, Plus, RotateCcw, Trash2, Upload } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { isApiError } from '@/api/client'
import { useTypes } from '@/api/hooks'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import type { CsvImportResponse, CsvParseResponse } from './api'
import { useCsvFields, useCsvImport, useCsvParse, useTemplates } from './hooks'
import { guessMapping } from './mapping'
import { FormField, NATIVE_SELECT, Notice, readFileText, WizardStepper } from './parts'

const SEPARATORS = [
  { value: ',', key: 'comma' },
  { value: ';', key: 'semicolon' },
  { value: 'tab', key: 'tab' },
  { value: '|', key: 'pipe' },
] as const

const IGNORE = ''

interface FixedRow {
  id: number
  field: string
  value: string
}

export function ImportCsvTab() {
  const { t } = useTranslation()
  const types = useTypes()
  const creatable = useMemo(() => (types.data ?? []).filter((x) => x.can_create), [types.data])
  const [chosenType, setType] = useState('')
  const [separator, setSeparator] = useState(',')
  const [hasHeader, setHasHeader] = useState(true)
  const [text, setText] = useState('')
  const [template, setTemplate] = useState('')
  const [parsed, setParsed] = useState<CsvParseResponse | null>(null)
  const [overrides, setOverrides] = useState<Record<number, string>>({})
  const [fixed, setFixed] = useState<FixedRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<CsvImportResponse | null>(null)

  const type = chosenType || creatable[0]?.name || ''
  const parse = useCsvParse()
  const importer = useCsvImport(type)
  const templates = useTemplates(type)
  const fieldsQuery = useCsvFields(type, template || null)
  const fields = useMemo(() => fieldsQuery.data ?? [], [fieldsQuery.data])

  const steps = [
    { id: 1, label: t('settingsUI.io.wizard.stepUpload') },
    { id: 2, label: t('settingsUI.io.wizard.stepPreview') },
    { id: 3, label: t('settingsUI.io.wizard.stepConfirm') },
    { id: 4, label: t('settingsUI.io.wizard.stepReport') },
  ]

  // columns are pre-mapped from their headers; what the user picks wins
  const mapping = useMemo(
    () => ({ ...(parsed ? guessMapping(parsed.columns, fields) : {}), ...overrides }),
    [parsed, fields, overrides],
  )

  const reset = () => {
    setOutcome(null)
    setError(null)
  }

  const load = async (content: string) => {
    reset()
    setParsed(null)
    setOverrides({})
    try {
      setParsed(await parse.mutateAsync({ text: content, separator, has_header: hasHeader }))
    } catch (e) {
      setError(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const onFile = async (file: File | undefined) => {
    if (!file) return
    const content = await readFileText(file)
    setText(content)
    await load(content)
  }

  const submit = async () => {
    reset()
    const picked = Object.entries(mapping)
      .filter(([, field]) => field !== IGNORE)
      .map(([column, field]) => ({ column: Number(column), field }))
    const values: Record<string, string> = {}
    for (const row of fixed) if (row.field && row.value !== '') values[row.field] = row.value
    try {
      const res = await importer.mutateAsync({
        text,
        separator,
        has_header: hasHeader,
        mapping: picked,
        fixed: values,
        template: template || null,
        base: null,
      })
      setOutcome(res)
    } catch (e) {
      setError(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const canImport = parsed !== null && parsed.total > 0 && Object.values(mapping).some(Boolean)
  const currentStep = outcome ? 4 : parsed ? 2 : 1

  const resetAll = () => {
    setText('')
    setParsed(null)
    setOverrides({})
    setFixed([])
    reset()
  }

  return (
    <Card className="border shadow-xs">
      <CardHeader className="border-b pb-4">
        <div className="space-y-1">
          <CardTitle>{t('io.csv.title')}</CardTitle>
          <p className="text-small text-muted-foreground">{t('io.csv.notice')}</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-5 p-5">
        <WizardStepper steps={steps} currentStep={currentStep} />

        <Notice>{t('io.csv.notice')}</Notice>

        {/* Step 1: Upload & Options */}
        <div className="grid gap-4 md:grid-cols-3">
          <FormField id="csv-type" label={t('io.csv.type')}>
            <select
              id="csv-type"
              className={NATIVE_SELECT}
              value={type}
              onChange={(e) => {
                setType(e.target.value)
                setTemplate('')
                setFixed([])
                setOverrides({})
                setParsed(null)
                reset()
              }}
            >
              {creatable.map((x) => (
                <option key={x.name} value={x.name}>
                  {x.label}
                </option>
              ))}
            </select>
          </FormField>
          <FormField id="csv-separator" label={t('io.csv.separator')}>
            <select
              id="csv-separator"
              className={NATIVE_SELECT}
              value={separator}
              onChange={(e) => {
                setSeparator(e.target.value)
                setParsed(null)
              }}
            >
              {SEPARATORS.map((s) => (
                <option key={s.value} value={s.value}>
                  {t(`io.csv.separators.${s.key}`)}
                </option>
              ))}
            </select>
          </FormField>
          {(templates.data?.length ?? 0) > 0 && (
            <FormField id="csv-template" label={t('io.csv.template')} hint={t('io.csv.templateHelp')}>
              <select
                id="csv-template"
                className={NATIVE_SELECT}
                value={template}
                onChange={(e) => {
                  setTemplate(e.target.value)
                  setFixed([])
                  setOverrides({})
                }}
                aria-describedby="csv-template-hint"
              >
                <option value="">{t('io.csv.noTemplate')}</option>
                {templates.data?.map((x) => (
                  <option key={x.dn} value={x.dn}>
                    {x.name}
                  </option>
                ))}
              </select>
            </FormField>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Checkbox
            id="csv-header"
            checked={hasHeader}
            onCheckedChange={(v) => {
              setHasHeader(v === true)
              setParsed(null)
            }}
          />
          <Label htmlFor="csv-header" className="text-body font-medium">
            {t('io.csv.hasHeader')}
          </Label>
        </div>

        <FormField id="csv-file" label={t('io.csv.file')}>
          <input
            id="csv-file"
            type="file"
            accept=".csv,.txt,text/csv,text/plain"
            onChange={(e) => void onFile(e.target.files?.[0])}
            className="block w-full text-body file:mr-3 file:h-8 file:rounded-md file:border file:border-input file:bg-card file:px-3 file:text-body file:font-medium"
          />
        </FormField>
        <FormField id="csv-text" label={t('io.csv.text')}>
          <Textarea
            id="csv-text"
            className="min-h-32 font-mono text-xs"
            spellCheck={false}
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setParsed(null)
              reset()
            }}
          />
        </FormField>
        <Button variant="outline" onClick={() => void load(text)} disabled={!text.trim() || parse.isPending}>
          <Upload className="size-4" aria-hidden />
          {t('io.csv.load')}
        </Button>

        {error && <Notice tone="error">{error}</Notice>}

        {/* Step 2 & 3: Preview, Mapping, Fixed Values & Confirmation */}
        {parsed && (
          <div className="space-y-6 border-t pt-5">
            <section aria-labelledby="csv-mapping-title" className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 id="csv-mapping-title" className="text-body font-semibold">
                    {t('io.csv.mapping')}
                  </h3>
                  <p className="text-xs text-muted-foreground">{t('io.csv.mappingHelp')}</p>
                </div>
                <Badge variant="neutral">
                  {parsed.columns.length} columns detected
                </Badge>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {parsed.columns.map((name, index) => (
                  <div key={index} className="flex items-center gap-2 rounded-md border bg-muted/20 p-2">
                    <Label htmlFor={`csv-col-${index}`} className="w-36 shrink-0 truncate font-mono text-xs">
                      {name}
                    </Label>
                    <select
                      id={`csv-col-${index}`}
                      className={NATIVE_SELECT}
                      value={mapping[index] ?? IGNORE}
                      onChange={(e) => setOverrides({ ...overrides, [index]: e.target.value })}
                    >
                      <option value={IGNORE}>{t('io.csv.ignore')}</option>
                      {fields.map((f) => (
                        <option key={f.key} value={f.key}>
                          {f.tab_label} / {f.label}
                          {f.required ? ' *' : ''}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            </section>

            <section aria-labelledby="csv-fixed-title" className="space-y-3">
              <div>
                <h3 id="csv-fixed-title" className="text-body font-semibold">
                  {t('io.csv.fixed')}
                </h3>
                <p className="text-xs text-muted-foreground">{t('io.csv.fixedHelp')}</p>
              </div>
              {fixed.map((row) => (
                <div key={row.id} className="flex items-center gap-2">
                  <select
                    aria-label={t('io.csv.fixedField')}
                    className={NATIVE_SELECT}
                    value={row.field}
                    onChange={(e) =>
                      setFixed(fixed.map((r) => (r.id === row.id ? { ...r, field: e.target.value } : r)))
                    }
                  >
                    <option value="">{t('io.csv.chooseField')}</option>
                    {fields.map((f) => (
                      <option key={f.key} value={f.key}>
                        {f.tab_label} / {f.label}
                      </option>
                    ))}
                  </select>
                  <Input
                    aria-label={t('io.csv.fixedValue')}
                    value={row.value}
                    onChange={(e) =>
                      setFixed(fixed.map((r) => (r.id === row.id ? { ...r, value: e.target.value } : r)))
                    }
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t('io.csv.removeFixed')}
                    onClick={() => setFixed(fixed.filter((r) => r.id !== row.id))}
                  >
                    <Trash2 className="size-4" aria-hidden />
                  </Button>
                </div>
              ))}
              <Button
                variant="outline"
                size="sm"
                onClick={() => setFixed([...fixed, { id: Date.now() + fixed.length, field: '', value: '' }])}
              >
                <Plus className="size-4" aria-hidden />
                {t('io.csv.addFixed')}
              </Button>
            </section>

            <section aria-labelledby="csv-preview-title" className="space-y-3">
              <h3 id="csv-preview-title" className="text-body font-semibold">
                {t('io.csv.preview', { count: parsed.rows.length, total: parsed.total })}
              </h3>
              <div className="max-h-64 overflow-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      {parsed.columns.map((c, i) => (
                        <TableHead key={i} className="font-mono text-xs">
                          {c}
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {parsed.rows.map((row, r) => (
                      <TableRow key={r}>
                        {parsed.columns.map((_, c) => (
                          <TableCell key={c} className="text-xs">
                            {row[c] ?? ''}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </section>

            {/* Confirm & execute */}
            <div className="flex items-center gap-3 border-t pt-4">
              <Button onClick={() => void submit()} disabled={!canImport || importer.isPending}>
                {t('io.csv.import')}
              </Button>
              {outcome && (
                <Button variant="ghost" onClick={resetAll}>
                  <RotateCcw className="size-4 mr-1" />
                  {t('settingsUI.io.wizard.reset')}
                </Button>
              )}
            </div>
          </div>
        )}

        {/* Step 4: Outcome report */}
        {outcome && (
          <section aria-live="polite" className="space-y-3 rounded-md border bg-card p-4">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="size-5 text-success" />
              <p className="text-body font-semibold text-foreground">
                {t('io.csv.imported', { count: outcome.imported })}
              </p>
            </div>
            {outcome.results
              .filter((r) => r.error)
              .map((r) => (
                <p key={r.line} role="alert" className="text-body text-destructive font-medium">
                  {t('io.csv.failedLine', { line: r.line, error: r.error })}
                </p>
              ))}
          </section>
        )}
      </CardContent>
    </Card>
  )
}

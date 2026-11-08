import { CheckCircle2, FileUp, Play, RotateCcw, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { isApiError } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { LdifAction, LdifImportResponse } from './api'
import { useLdifImport } from './hooks'
import { FormField, Notice, readFileText, WizardStepper } from './parts'

const TONE: Record<LdifAction, 'success' | 'primary' | 'neutral' | 'warning' | 'destructive'> = {
  add: 'success',
  modify: 'primary',
  unchanged: 'neutral',
  exists: 'warning',
  error: 'destructive',
}

export function ResultTable({ data }: { data: LdifImportResponse }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2" aria-label={t('io.ldif.summary')}>
        {(Object.keys(TONE) as LdifAction[]).map((a) => (
          <Badge key={a} variant={TONE[a]}>
            {t(`io.ldif.actions.${a}`)}: {data.summary[a]}
          </Badge>
        ))}
      </div>
      <div className="max-h-80 overflow-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">#</TableHead>
              <TableHead>DN</TableHead>
              <TableHead>{t('io.ldif.result')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.results.map((r) => (
              <TableRow key={r.index}>
                <TableCell className="font-mono text-xs text-muted-foreground">{r.index}</TableCell>
                <TableCell className="font-mono text-xs break-all">{r.dn}</TableCell>
                <TableCell>
                  <Badge variant={TONE[r.action]}>{t(`io.ldif.actions.${r.action}`)}</Badge>
                  {r.error && <span className="ml-2 text-xs text-destructive">{r.error}</span>}
                  {!r.error && r.changes.length > 0 && (
                    <span className="ml-2 font-mono text-xs text-muted-foreground">
                      {r.changes.join(', ')}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

export function ImportLdifTab() {
  const { t } = useTranslation()
  const mutation = useLdifImport()
  const [text, setText] = useState('')
  const [overwrite, setOverwrite] = useState(false)
  const [removeMissing, setRemoveMissing] = useState(false)
  const [previewed, setPreviewed] = useState(false)
  const [result, setResult] = useState<LdifImportResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const steps = [
    { id: 1, label: t('settingsUI.io.wizard.stepUpload') },
    { id: 2, label: t('settingsUI.io.wizard.stepPreview') },
    { id: 3, label: t('settingsUI.io.wizard.stepConfirm') },
    { id: 4, label: t('settingsUI.io.wizard.stepReport') },
  ]

  const change = (fn: () => void) => {
    fn()
    setPreviewed(false)
    setResult(null)
    setError(null)
  }

  const run = async (dryRun: boolean) => {
    setError(null)
    try {
      const data = await mutation.mutateAsync({
        text,
        overwrite,
        remove_missing: overwrite && removeMissing,
        dry_run: dryRun,
      })
      setResult(data)
      setPreviewed(dryRun)
    } catch (e) {
      setResult(null)
      setPreviewed(false)
      setError(isApiError(e) ? e.message : t('common.error'))
    }
  }

  const onFile = async (file: File | undefined) => {
    if (!file) return
    const content = await readFileText(file)
    change(() => setText(content))
  }

  const resetAll = () => {
    setText('')
    setOverwrite(false)
    setRemoveMissing(false)
    setPreviewed(false)
    setResult(null)
    setError(null)
  }

  const currentStepNum = result && !result.dry_run ? 4 : previewed ? 2 : 1

  return (
    <Card className="border shadow-xs">
      <CardHeader className="border-b pb-4">
        <CardTitle>{t('io.ldif.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5 p-5">
        <WizardStepper steps={steps} currentStep={currentStepNum} />

        <div className="flex items-start gap-2 rounded-sm border border-warning/30 bg-warning-soft p-2.5 text-body text-warning">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{t('io.ldif.restricted')}</span>
        </div>

        {/* Step 1: Upload & Options */}
        <div className="space-y-4">
          <FormField id="ldif-file" label={t('io.ldif.file')}>
            <input
              id="ldif-file"
              type="file"
              accept=".ldif,.txt,text/plain"
              onChange={(e) => void onFile(e.target.files?.[0])}
              className="block w-full text-body file:mr-3 file:h-8 file:rounded-md file:border file:border-input file:bg-card file:px-3 file:text-body file:font-medium"
            />
          </FormField>
          <FormField id="ldif-text" label={t('io.ldif.text')}>
            <Textarea
              id="ldif-text"
              className="min-h-48 font-mono text-xs"
              spellCheck={false}
              value={text}
              onChange={(e) => change(() => setText(e.target.value))}
              placeholder={'dn: ou=example,dc=example,dc=com\nobjectClass: organizationalUnit\nou: example'}
            />
          </FormField>
          <div className="space-y-2 rounded-md border bg-muted/20 p-3">
            <div className="flex items-center gap-2">
              <Checkbox
                id="ldif-overwrite"
                checked={overwrite}
                onCheckedChange={(v) => change(() => setOverwrite(v === true))}
              />
              <Label htmlFor="ldif-overwrite" className="text-body font-medium">
                {t('io.ldif.overwrite')}
              </Label>
            </div>
            <div className="flex items-center gap-2 pl-6">
              <Checkbox
                id="ldif-remove"
                checked={overwrite && removeMissing}
                disabled={!overwrite}
                onCheckedChange={(v) => change(() => setRemoveMissing(v === true))}
              />
              <Label
                htmlFor="ldif-remove"
                className={cn('text-body', !overwrite && 'opacity-60')}
              >
                {t('io.ldif.removeMissing')}
              </Label>
            </div>
          </div>
        </div>

        {error && <Notice tone="error">{error}</Notice>}

        {/* Action buttons */}
        <div className="flex flex-wrap items-center gap-2 border-t pt-4">
          <Button
            variant="outline"
            onClick={() => void run(true)}
            disabled={!text.trim() || mutation.isPending}
          >
            <FileUp className="size-4" aria-hidden />
            {t('io.ldif.preview')}
          </Button>
          <Button
            onClick={() => void run(false)}
            disabled={!previewed || mutation.isPending}
          >
            <Play className="size-4" aria-hidden />
            {t('io.ldif.apply')}
          </Button>
          {result && !result.dry_run && (
            <Button variant="ghost" onClick={resetAll} className="ml-auto">
              <RotateCcw className="size-4 mr-1" />
              {t('settingsUI.io.wizard.reset')}
            </Button>
          )}
        </div>

        {/* Preview / Results */}
        {result && (
          <div className="space-y-3 rounded-md border bg-card p-4">
            <div className="flex items-center justify-between border-b pb-2">
              <h3 className="text-body font-semibold">
                {result.dry_run ? t('io.ldif.previewTitle') : t('io.ldif.appliedTitle')}
              </h3>
              {!result.dry_run && (
                <Badge variant="success" className="gap-1">
                  <CheckCircle2 className="size-3" />
                  {t('settingsUI.io.wizard.successTitle')}
                </Badge>
              )}
            </div>
            <ResultTable data={result} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

import { AlertCircle, Check, Info } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

export const NATIVE_SELECT =
  'h-8 w-full rounded-md border border-input bg-card px-2.5 text-body outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/25 disabled:opacity-50'

export function FormField({
  id,
  label,
  hint,
  children,
  className,
}: {
  id: string
  label: string
  hint?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('space-y-1.5', className)}>
      <Label htmlFor={id} className="text-body font-medium">
        {label}
      </Label>
      {children}
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  )
}

export function Notice({
  tone = 'info',
  children,
}: {
  tone?: 'info' | 'error'
  children: React.ReactNode
}) {
  const Icon = tone === 'error' ? AlertCircle : Info
  return (
    <div
      role={tone === 'error' ? 'alert' : 'note'}
      className={cn(
        'flex items-start gap-2 rounded-sm border p-2.5 text-body',
        tone === 'error'
          ? 'border-destructive/30 bg-destructive-soft text-destructive'
          : 'border-border bg-muted text-muted-foreground',
      )}
    >
      <Icon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span className="leading-snug">{children}</span>
    </div>
  )
}

export interface WizardStep {
  id: number
  label: string
}

export function WizardStepper({
  steps,
  currentStep,
  onStepClick,
}: {
  steps: WizardStep[]
  currentStep: number
  onStepClick?: (step: number) => void
}) {
  return (
    <nav aria-label="Import wizard steps" className="mb-5 border-b pb-4">
      <ol className="flex flex-wrap items-center gap-2 sm:gap-3">
        {steps.map((s, idx) => {
          const isDone = currentStep > s.id
          const isCurrent = currentStep === s.id
          const canClick = onStepClick && isDone
          return (
            <li key={s.id} className="flex items-center gap-2">
              <button
                type="button"
                disabled={!canClick}
                onClick={() => canClick && onStepClick(s.id)}
                className={cn(
                  'flex items-center gap-2 rounded-full py-1 px-2.5 text-caption font-medium transition-colors outline-none',
                  canClick && 'hover:bg-accent cursor-pointer',
                  !canClick && 'cursor-default',
                )}
                aria-current={isCurrent ? 'step' : undefined}
              >
                <span
                  className={cn(
                    'flex size-5 items-center justify-center rounded-full text-micro font-semibold transition-colors',
                    isDone
                      ? 'bg-primary text-primary-foreground'
                      : isCurrent
                        ? 'border-2 border-primary bg-background text-primary'
                        : 'border bg-muted/60 text-muted-foreground',
                  )}
                >
                  {isDone ? <Check className="size-3" /> : s.id}
                </span>
                <span
                  className={cn(
                    'font-medium text-caption',
                    isCurrent ? 'text-foreground font-semibold' : 'text-muted-foreground',
                  )}
                >
                  {s.label}
                </span>
              </button>
              {idx < steps.length - 1 && (
                <div
                  className={cn(
                    'h-px w-3 sm:w-6 transition-colors',
                    currentStep > s.id ? 'bg-primary' : 'bg-border',
                  )}
                  aria-hidden
                />
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

/** Read a text file picked by the user. */
export async function readFileText(file: File): Promise<string> {
  return await file.text()
}

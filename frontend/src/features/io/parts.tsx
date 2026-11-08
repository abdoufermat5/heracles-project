import { AlertCircle, Info } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

export const NATIVE_SELECT =
  'h-8 w-full rounded-md border border-input bg-card px-2.5 text-[13px] outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/25 disabled:opacity-50'

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
      <Label htmlFor={id} className="text-[13px] font-medium">
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
        'flex items-start gap-2 rounded-sm border p-2.5 text-[13px]',
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

/** Read a text file picked by the user. */
export async function readFileText(file: File): Promise<string> {
  return await file.text()
}

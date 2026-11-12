import type { ReactNode } from 'react'
import { PageHeader } from '@/components/ui/page-header'
import { cn } from '@/lib/utils'

/**
 * The frame of every console page: title, description and actions on top, an optional
 * toolbar (filters, tabs), then the content. The shell owns the outer padding and the
 * maximum width, so pages never add their own.
 */
export function PageLayout({
  title,
  description,
  actions,
  toolbar,
  children,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  toolbar?: ReactNode
  children?: ReactNode
  className?: string
}) {
  return (
    <div data-slot="page-layout" className={cn('space-y-4', className)}>
      <PageHeader title={title} description={description} actions={actions} className="pb-0" />
      {toolbar}
      {children}
    </div>
  )
}

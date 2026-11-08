import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/tooltip'
import '@/i18n'
import { setTechnicalDetails } from '@/lib/preferences'
import { BulkActionBar, ConfirmDialog, FactList, OrgPath, Pagination, SectionCard, StatusBadge } from '.'

const DN = 'uid=adurand,ou=people,ou=Sales,ou=Paris,dc=example,dc=com'

describe('patterns', () => {
  it('names account states in plain words', () => {
    render(<StatusBadge status="expired" />)
    expect(screen.getByText('Password expired')).toBeInTheDocument()
  })

  it('shows a readable location, and the DN only with technical details', () => {
    act(() => setTechnicalDetails(false))
    const { rerender } = render(
      <TooltipProvider>
        <OrgPath dn={DN} baseDn="dc=example,dc=com" />
      </TooltipProvider>,
    )
    expect(screen.getByText('Paris › Sales')).toBeInTheDocument()
    expect(screen.queryByText(DN)).not.toBeInTheDocument()

    act(() => setTechnicalDetails(true))
    rerender(
      <TooltipProvider>
        <OrgPath dn={DN} baseDn="dc=example,dc=com" />
      </TooltipProvider>,
    )
    expect(screen.getByText(DN)).toBeInTheDocument()
    act(() => setTechnicalDetails(false))
  })

  it('marks empty facts as not set', () => {
    render(<FactList items={[{ label: 'Mobile', value: null }]} />)
    expect(screen.getByText('Not set')).toBeInTheDocument()
  })

  it('requires the typed text before a destructive confirmation', async () => {
    const onConfirm = vi.fn()
    const user = userEvent.setup()
    render(
      <ConfirmDialog
        open
        onOpenChange={() => undefined}
        title="Delete Alice?"
        confirmLabel="Delete"
        destructive
        confirmText="adurand"
        onConfirm={onConfirm}
      />,
    )
    const button = screen.getByRole('button', { name: 'Delete' })
    expect(button).toBeDisabled()
    await user.type(screen.getByRole('textbox'), 'adurand')
    await user.click(button)
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('paginates and reports the range', async () => {
    const onPage = vi.fn()
    const user = userEvent.setup()
    render(<Pagination page={1} pageSize={50} total={120} onPage={onPage} />)
    expect(screen.getByText('1–50 of 120')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Next page' }))
    expect(onPage).toHaveBeenCalledWith(2)
  })

  it('shows the bulk bar only with a selection', () => {
    const { rerender } = render(
      <BulkActionBar count={0} onClear={() => undefined}>
        <button type="button">Lock</button>
      </BulkActionBar>,
    )
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
    rerender(
      <BulkActionBar count={3} onClear={() => undefined}>
        <button type="button">Lock</button>
      </BulkActionBar>,
    )
    expect(screen.getByRole('region')).toHaveTextContent('3 selected')
  })

  it('renders SectionCard with id and content', () => {
    render(
      <SectionCard id="test-card" title="Profile Details">
        <p>Card content</p>
      </SectionCard>,
    )
    const card = screen.getByText('Profile Details').closest('section')
    expect(card).toHaveAttribute('id', 'test-card')
    expect(screen.getByText('Card content')).toBeInTheDocument()
  })
})

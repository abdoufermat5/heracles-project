import { toast } from 'sonner'
import { showTriggerOutput } from '@/features/editor/triggerOutput'

vi.mock('sonner', () => ({
  toast: { warning: vi.fn(), message: vi.fn() },
}))

describe('trigger output', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows every warning and message returned by a write', () => {
    showTriggerOutput({ warnings: ['postmodify failed'], messages: ['saved to /srv'] })
    expect(toast.warning).toHaveBeenCalledWith('postmodify failed')
    expect(toast.message).toHaveBeenCalledWith('saved to /srv')
  })

  it('says nothing when the write reported no output', () => {
    showTriggerOutput({})
    showTriggerOutput(undefined)
    showTriggerOutput(null)
    expect(toast.warning).not.toHaveBeenCalled()
    expect(toast.message).not.toHaveBeenCalled()
  })
})

import { CalendarClock } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EndDateDialog } from './EndDateDialog'
import { endDay, useAclEndDates } from './hooks'

/**
 * End date of one member of an ACL assignment: the day it ends, and a button to set or clear it.
 *
 * Renders nothing without the access plugin. Meant for the lists of the permission matrix: it only
 * dates members that exist (the matrix saves membership itself), and refreshes with the access queries.
 */
export function AclMemberEndDate({
  holder,
  scope,
  role,
  member,
  name,
}: {
  /** Entry carrying the assignment. */
  holder: string
  /** Assignment scope: `subtree` or `base`. */
  scope: string
  /** DN of the assignment's ACL role. */
  role: string
  member: string
  name: string
}) {
  const { t } = useTranslation()
  const dates = useAclEndDates(holder)
  const [open, setOpen] = useState(false)
  if (!dates.available) return null
  const current = dates.find(scope, role, member)
  return (
    <>
      {current ? <Badge variant="outline">{t('grants.until', { day: endDay(current.until) })}</Badge> : null}
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="text-muted-foreground"
        title={t('grants.endDate.open', { name })}
        aria-label={t('grants.endDate.open', { name })}
        onClick={() => setOpen(true)}
      >
        <CalendarClock />
      </Button>
      {open ? (
        <EndDateDialog
          open
          onOpenChange={setOpen}
          holder={holder}
          kind="acl"
          member={member}
          memberName={name}
          current={current}
          aclScope={scope}
          aclRole={role}
        />
      ) : null}
    </>
  )
}

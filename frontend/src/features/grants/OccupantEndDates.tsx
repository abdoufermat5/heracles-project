import { CalendarClock } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { rdnValue } from '@/lib/objects'
import { EndDateDialog } from './EndDateDialog'
import { endDay, useEndDates } from './hooks'

/**
 * End dates of a role's occupants (the role editor's "Access ends" tab).
 *
 * Lists the saved occupants; dates apply to people who already hold the role. Not a <form>: it renders
 * inside the editor's own form.
 */
export function OccupantEndDates({ dn, occupants }: { dn: string; occupants: string[] }) {
  const { t } = useTranslation()
  const dates = useEndDates(dn, 'roleOccupant')
  const [dating, setDating] = useState<{ dn: string; name: string } | null>(null)

  return (
    <section aria-labelledby="occupant-dates-title" className="rounded-md border bg-card">
      <div className="border-b px-4 py-3">
        <h2 id="occupant-dates-title" className="text-body font-semibold text-foreground">
          {t('grants.occupants.title')}
        </h2>
        <p className="text-xs text-muted-foreground">{t('grants.occupants.help')}</p>
      </div>
      {occupants.length === 0 ? (
        <p className="p-4 text-small text-muted-foreground">{t('grants.occupants.empty')}</p>
      ) : (
        <table className="w-full text-left">
          <thead>
            <tr className="border-b text-caption text-muted-foreground">
              <th scope="col" className="px-4 py-2 font-medium">
                {t('grants.occupants.person')}
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                {t('grants.untilColumn')}
              </th>
              <th scope="col" className="px-4 py-2">
                <span className="sr-only">{t('grants.occupants.actions')}</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {occupants.map((occupant) => {
              const name = rdnValue(occupant)
              const current = dates.byMember.get(occupant.toLowerCase())
              return (
                <tr key={occupant}>
                  <td className="px-4 py-2.5 text-body" title={occupant}>
                    {name}
                  </td>
                  <td className="px-4 py-2.5 text-small">
                    {current ? (
                      <span className="text-foreground">{t('grants.until', { day: endDay(current.until) })}</span>
                    ) : (
                      <span className="text-muted-foreground">{t('grants.permanent')}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      className="text-muted-foreground"
                      title={t('grants.endDate.open', { name })}
                      aria-label={t('grants.endDate.open', { name })}
                      onClick={() => setDating({ dn: occupant, name })}
                    >
                      <CalendarClock className="size-3.5" />
                    </Button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {dating ? (
        <EndDateDialog
          key={dating.dn}
          open
          onOpenChange={(o) => !o && setDating(null)}
          holder={dn}
          kind="roleOccupant"
          member={dating.dn}
          memberName={dating.name}
          current={dates.byMember.get(dating.dn.toLowerCase())}
        />
      ) : null}
    </section>
  )
}

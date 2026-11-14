import { useEffect } from 'react'
import { useObject, useTypeDescriptor } from '@/api/hooks'
import { nameValue } from '@/lib/objects'
import { addRecentItem } from './recent'

/**
 * Records the object whose page is open in the "recent objects" list (dashboard and
 * command palette). It reads the same cached queries as the page, so no extra request is
 * made, and it only records once the object really loaded: a missing object never enters
 * the list.
 */
export function RecentTracker({ type, dn }: { type: string; dn: string }) {
  const { data: desc } = useTypeDescriptor(type)
  const { data: detail } = useObject(type, dn)
  const title = desc && detail ? nameValue(desc, detail) : null
  useEffect(() => {
    if (title) addRecentItem({ dn, type, title, subtitle: dn })
  }, [dn, type, title])
  return null
}

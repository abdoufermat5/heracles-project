import type { Control } from 'react-hook-form'
import type { AttributeDescriptor, ObjectDetail, SectionDescriptor } from '@/api/types'
import { SectionCard } from '@/components/patterns/SectionCard'
import { attrRight, type FormValues } from '@/lib/objects'
import { FieldRow } from './FieldRow'

interface Props {
  section: SectionDescriptor
  tabName: string
  control: Control<FormValues>
  acl: ObjectDetail['acl'] | undefined
  isCreate: boolean
  readOnlyMode: boolean
}

export function EditorSection({
  section,
  tabName,
  control,
  acl,
  isCreate,
  readOnlyMode,
}: Props) {
  const visible = section.attributes.filter((a) => {
    if (a.kind === 'hidden') return false
    if (isCreate && a.kind === 'display') return false
    return attrRight(acl, tabName, a) !== 'hidden'
  })

  if (visible.length === 0) return null

  return (
    <SectionCard title={section.label} className="w-full">
      <div className="grid grid-cols-1 gap-x-8 gap-y-4 md:grid-cols-2">
        {visible.map((a: AttributeDescriptor) => {
          const right = attrRight(acl, tabName, a)
          const ro = readOnlyMode || right !== 'rw' || (a.readonly === true && !isCreate)
          return (
            <FieldRow
              key={a.name}
              control={control}
              tab={tabName}
              attr={a}
              readOnly={ro}
            />
          )
        })}
      </div>
    </SectionCard>
  )
}

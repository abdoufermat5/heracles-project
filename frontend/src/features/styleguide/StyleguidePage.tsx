import {
  Building2,
  KeyRound,
  Lock,
  Mail,
  MoreHorizontal,
  Phone,
  Plus,
  ShieldCheck,
  Users,
  UserPlus,
} from 'lucide-react'
import { useState } from 'react'
import {
  BulkActionBar,
  ConfirmDialog,
  EntityHeader,
  FactList,
  FilterBar,
  FilterChip,
  OrgPath,
  Pagination,
  SectionCard,
  StatusBadge,
  type AccountStatus,
} from '@/components/patterns'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/ui/page-header'
import { Switch } from '@/components/ui/switch'
import { setTechnicalDetails, useTechnicalDetails } from '@/lib/preferences'
import { initials } from '@/lib/utils'

/*
 * Living reference of the console's visual language. Not linked from the
 * navigation; reviewers open /styleguide. Strings here are sample content.
 */

const BASE = 'dc=example,dc=com'
const PEOPLE: { name: string; login: string; dn: string; status: AccountStatus; groups: number }[] = [
  { name: 'Alice Durand', login: 'adurand', dn: `uid=adurand,ou=people,ou=Sales,ou=Paris,${BASE}`, status: 'active', groups: 4 },
  { name: 'Bruno Michel', login: 'bmichel', dn: `uid=bmichel,ou=people,ou=Engineering,ou=Paris,${BASE}`, status: 'locked', groups: 2 },
  { name: 'Chloé Petit', login: 'cpetit', dn: `uid=cpetit,ou=people,ou=Support,ou=Lyon,${BASE}`, status: 'expired', groups: 3 },
  { name: 'David Roux', login: 'droux', dn: `uid=droux,ou=people,ou=Lyon,${BASE}`, status: 'disabled', groups: 0 },
  { name: 'Emma Faure', login: 'efaure', dn: `uid=efaure,ou=people,ou=Sales,ou=Paris,${BASE}`, status: 'pending', groups: 1 },
]

function Swatch({ name, className }: { name: string; className: string }) {
  return (
    <div className="space-y-1.5">
      <div className={`h-12 rounded-md border ${className}`} />
      <div className="text-caption text-muted-foreground">{name}</div>
    </div>
  )
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="label-caps">{title}</h2>
      {children}
    </section>
  )
}

export function StyleguidePage() {
  const technical = useTechnicalDetails()
  const [editing, setEditing] = useState(false)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<string[]>(['locked'])
  const [selected, setSelected] = useState<string[]>([])
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [confirm, setConfirm] = useState(false)

  return (
    <div className="mx-auto max-w-6xl space-y-10 pb-24">
      <PageHeader
        title="Style guide"
        description="The building blocks every page uses. Light and dark follow the theme switch."
        actions={
          <label className="flex items-center gap-2 text-small text-muted-foreground">
            <Switch checked={technical} onCheckedChange={setTechnicalDetails} />
            Show technical details
          </label>
        }
      />

      <Block title="Colour">
        <div className="grid grid-cols-3 gap-4 sm:grid-cols-6">
          <Swatch name="Background" className="bg-background" />
          <Swatch name="Surface" className="bg-card" />
          <Swatch name="Primary" className="bg-primary" />
          <Swatch name="Primary soft" className="bg-primary-soft" />
          <Swatch name="Muted" className="bg-muted" />
          <Swatch name="Border" className="bg-border" />
          <Swatch name="Success" className="bg-success" />
          <Swatch name="Warning" className="bg-warning" />
          <Swatch name="Danger" className="bg-destructive" />
          <Swatch name="Success soft" className="bg-success-soft" />
          <Swatch name="Warning soft" className="bg-warning-soft" />
          <Swatch name="Danger soft" className="bg-destructive-soft" />
        </div>
      </Block>

      <Block title="Type">
        <div className="space-y-2 rounded-lg border bg-card p-5">
          <p className="text-title font-semibold tracking-tight">Title — Alice Durand</p>
          <p className="text-lead font-semibold">Lead — Account and access</p>
          <p className="text-body">Body — Everyday text, table cells, form values and buttons.</p>
          <p className="text-small text-muted-foreground">Small — Help text and secondary facts.</p>
          <p className="text-caption text-muted-foreground">Caption — Badges and counters.</p>
          <p className="label-caps">Section label</p>
        </div>
      </Block>

      <Block title="Actions and inputs">
        <div className="flex flex-wrap items-center gap-2">
          <Button>
            <UserPlus />
            New person
          </Button>
          <Button variant="outline">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Delete</Button>
          <Button size="sm" variant="outline">
            Small
          </Button>
          <Button size="icon" variant="outline" aria-label="More">
            <MoreHorizontal />
          </Button>
        </div>
        <div className="grid max-w-xl gap-4 sm:grid-cols-2">
          <div className="grid gap-1.5">
            <Label htmlFor="sg-first">First name</Label>
            <Input id="sg-first" placeholder="Alice" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="sg-mail">Email</Label>
            <Input id="sg-mail" placeholder="alice@example.com" />
            <p className="text-small text-muted-foreground">Used for password recovery.</p>
          </div>
        </div>
      </Block>

      <Block title="Status">
        <div className="flex flex-wrap items-center gap-2">
          {(['active', 'locked', 'expired', 'disabled', 'pending'] as const).map((s) => (
            <StatusBadge key={s} status={s} />
          ))}
          <Badge variant="neutral">Employee</Badge>
          <Badge variant="outline">Template</Badge>
        </div>
      </Block>

      <Block title="Record header">
        <div className="rounded-lg border bg-card p-6">
          <EntityHeader
            name="Alice Durand"
            subtitle="Account manager"
            badges={<StatusBadge status="active" />}
            meta={[
              { icon: <Building2 />, content: <OrgPath dn={PEOPLE[0]!.dn} baseDn={BASE} showIcon={false} /> },
              { icon: <Mail />, content: 'alice.durand@example.com' },
              { icon: <Phone />, content: '+33 1 23 45 67 89' },
            ]}
            actions={
              <>
                <Button variant="outline">
                  <KeyRound />
                  Reset password
                </Button>
                <Button variant="outline">
                  <Lock />
                  Lock
                </Button>
                <Button variant="outline" size="icon" aria-label="More actions">
                  <MoreHorizontal />
                </Button>
              </>
            }
          />
          <EntityHeader
            className="border-t pt-5 pb-0"
            name="Sales team"
            icon={<Users />}
            subtitle="Everyone selling in France"
            badges={<Badge variant="neutral">42 members</Badge>}
            actions={
              <Button>
                <Plus />
                Add members
              </Button>
            }
          />
        </div>
      </Block>

      <Block title="Sections">
        <div className="grid gap-4 lg:grid-cols-2">
          <SectionCard
            title="Contact"
            description="How colleagues reach this person."
            editable
            editing={editing}
            onEdit={() => setEditing(true)}
            onCancel={() => setEditing(false)}
            onSave={() => setEditing(false)}
          >
            {editing ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label htmlFor="sg-phone">Phone</Label>
                  <Input id="sg-phone" defaultValue="+33 1 23 45 67 89" />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="sg-mobile">Mobile</Label>
                  <Input id="sg-mobile" />
                </div>
              </div>
            ) : (
              <FactList
                items={[
                  { label: 'Email', value: 'alice.durand@example.com' },
                  { label: 'Phone', value: '+33 1 23 45 67 89' },
                  { label: 'Mobile', value: null },
                  { label: 'Office', value: 'Paris, 3rd floor' },
                ]}
              />
            )}
          </SectionCard>
          <SectionCard title="Sign-in security" actions={<StatusBadge status="active" />}>
            <FactList
              columns={1}
              items={[
                { label: 'Two-factor authentication', value: 'Authenticator app and 1 security key' },
                { label: 'Password', value: 'Changed 12 days ago · expires in 78 days' },
              ]}
            />
          </SectionCard>
        </div>
      </Block>

      <Block title="Lists">
        <div className="space-y-3">
          <FilterBar
            search={search}
            onSearch={setSearch}
            placeholder="Search people"
            end={
              <Button size="sm">
                <UserPlus />
                New person
              </Button>
            }
          >
            <FilterChip
              label="Status"
              options={[
                { value: 'active', label: 'Active', count: 180 },
                { value: 'locked', label: 'Locked', count: 12 },
                { value: 'expired', label: 'Password expired', count: 8 },
              ]}
              selected={status}
              onChange={setStatus}
            />
            <FilterChip
              label="Department"
              options={[
                { value: 'paris', label: 'Paris' },
                { value: 'lyon', label: 'Lyon' },
              ]}
              selected={[]}
              onChange={() => undefined}
            />
          </FilterBar>
          <div className="overflow-hidden rounded-lg border bg-card">
            <table className="w-full text-body">
              <thead className="border-b bg-muted/40 text-left text-small text-muted-foreground">
                <tr>
                  <th className="w-10 px-4 py-2.5">
                    <Checkbox
                      aria-label="Select all"
                      checked={selected.length === PEOPLE.length}
                      onCheckedChange={(on) => setSelected(on ? PEOPLE.map((p) => p.login) : [])}
                    />
                  </th>
                  <th className="px-3 py-2.5 font-medium">Person</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="hidden px-3 py-2.5 font-medium md:table-cell">Department</th>
                  <th className="hidden px-3 py-2.5 text-right font-medium sm:table-cell">Groups</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {PEOPLE.map((p) => (
                  <tr key={p.login} className="hover:bg-muted/40" data-state={selected.includes(p.login) ? 'selected' : undefined}>
                    <td className="px-4 py-2.5">
                      <Checkbox
                        aria-label={`Select ${p.name}`}
                        checked={selected.includes(p.login)}
                        onCheckedChange={(on) =>
                          setSelected(on ? [...selected, p.login] : selected.filter((x) => x !== p.login))
                        }
                      />
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-3">
                        <Avatar className="size-8">
                          <AvatarFallback className="bg-primary-soft text-caption font-semibold text-primary">
                            {initials(p.name)}
                          </AvatarFallback>
                        </Avatar>
                        <div className="min-w-0">
                          <div className="truncate font-medium text-foreground">{p.name}</div>
                          <div className="truncate text-small text-muted-foreground">{p.login}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <StatusBadge status={p.status} />
                    </td>
                    <td className="hidden px-3 py-2.5 md:table-cell">
                      <OrgPath dn={p.dn} baseDn={BASE} />
                    </td>
                    <td className="hidden px-3 py-2.5 text-right tabular-nums sm:table-cell">{p.groups}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="border-t px-4 py-2.5">
              <Pagination page={page} pageSize={pageSize} total={200} onPage={setPage} onPageSize={setPageSize} />
            </div>
          </div>
          <BulkActionBar count={selected.length} onClear={() => setSelected([])}>
            <Button variant="ghost" size="sm">
              <Lock />
              Lock
            </Button>
            <Button variant="ghost" size="sm">
              <Users />
              Add to group
            </Button>
          </BulkActionBar>
        </div>
      </Block>

      <Block title="Empty and confirm">
        <div className="grid gap-4 lg:grid-cols-2">
          <EmptyState
            icon={<ShieldCheck />}
            title="No roles yet"
            description="Roles bundle permissions you can give to people and groups."
            action={
              <Button size="sm">
                <Plus />
                Create a role
              </Button>
            }
          />
          <div className="flex items-center justify-center rounded-lg border bg-card p-6">
            <Button variant="destructive" onClick={() => setConfirm(true)}>
              Delete Alice Durand…
            </Button>
          </div>
        </div>
        <ConfirmDialog
          open={confirm}
          onOpenChange={setConfirm}
          title="Delete Alice Durand?"
          description="Her account, group memberships and saved versions are removed. This cannot be undone."
          confirmLabel="Delete person"
          destructive
          confirmText="adurand"
          onConfirm={() => setConfirm(false)}
        />
      </Block>
    </div>
  )
}

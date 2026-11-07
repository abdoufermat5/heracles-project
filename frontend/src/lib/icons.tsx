import {
  Box,
  Building2,
  Globe,
  Key,
  Mail,
  Network,
  Server,
  Settings,
  Shield,
  User,
  Users,
  Workflow,
  type LucideIcon,
} from 'lucide-react'

const map: Record<string, LucideIcon> = {
  user: User,
  users: Users,
  shield: Shield,
  'building-2': Building2,
  globe: Globe,
  server: Server,
  mail: Mail,
  network: Network,
  key: Key,
  workflow: Workflow,
  settings: Settings,
}

export function TypeIcon({ name, className }: { name: string; className?: string }) {
  const Icon = map[name] ?? Box
  return <Icon className={className} aria-hidden />
}

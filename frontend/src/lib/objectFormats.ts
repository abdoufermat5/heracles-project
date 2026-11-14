/**
 * Formats of object attribute values, mirrored from `backend/src/heracles/core/object_formats.py`
 * and the plugins that register their own (sudo, DNS): an attribute value the editor refuses is
 * refused by the API too. A descriptor names one in `constraints.format`, or one per sibling
 * value in `constraints.format_by`. Messages live under `objectFormats.<name>`.
 */
import { matchesFormat, registerFormat } from './formats'

const IPV4 = '(?:(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)\\.){3}(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)'
const IPV4_RE = new RegExp(`^${IPV4}$`)
const HEX_GROUP_RE = /^[0-9A-Fa-f]{1,4}$/

export function isIpv4(v: string): boolean {
  return IPV4_RE.test(v)
}

/** Number of 16-bit groups in a colon-separated run, `null` when a group is malformed. */
function groupCount(run: string, allowIpv4Tail: boolean): number | null {
  if (run === '') return 0
  const groups = run.split(':')
  let count = 0
  for (let i = 0; i < groups.length; i++) {
    const g = groups[i] ?? ''
    if (g.includes('.')) {
      if (!allowIpv4Tail || i !== groups.length - 1 || !isIpv4(g)) return null
      count += 2
    } else if (HEX_GROUP_RE.test(g)) {
      count += 1
    } else {
      return null
    }
  }
  return count
}

export function isIpv6(v: string): boolean {
  if (!/^[0-9A-Fa-f:.]+$/.test(v)) return false
  const halves = v.split('::')
  if (halves.length > 2) return false
  if (halves.length === 1) return groupCount(v, true) === 8
  const left = groupCount(halves[0] ?? '', false)
  const right = groupCount(halves[1] ?? '', true)
  return left !== null && right !== null && left + right <= 7
}

const isIp = (v: string): boolean => isIpv4(v) || isIpv6(v)

const SSH_KEY_RE =
  /^(?:(?:[^\s"]|"(?:[^"\\]|\\.)*")+\s+)?(?:disabled-)?(?:ssh-(?:dss|rsa|ed25519)|ecdsa-sha2-nistp\d{3}|ecdsa-sk|ed25519-sk|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)\s+([A-Za-z0-9+/]+={0,2})(?:\s+\S.*)?$/

function isSshKey(v: string): boolean {
  const m = SSH_KEY_RE.exec(v.trim())
  return m !== null && (m[1] ?? '').length % 4 === 0
}

const MAC_RE = /^(?:[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}|[0-9A-Fa-f]{12})$/
const SID_RE = /^S-1-\d+(?:-\d+)+$/
// eslint-disable-next-line no-control-regex
const CONTROL_RE = /[\x00-\x1f\x7f]/

// --- sudo -----------------------------------------------------------------

const SUDO_NAME = '[A-Za-z0-9_][A-Za-z0-9_.@-]*\\$?'
const SUDO_USER_RE = new RegExp(
  `^(?:ALL|${SUDO_NAME}|%:?${SUDO_NAME}|%#[0-9]+|#[0-9]+|\\+${SUDO_NAME})$`,
)
const SUDO_RUNAS_GROUP_RE = new RegExp(`^(?:ALL|${SUDO_NAME}|#[0-9]+)$`)
const SUDO_HOSTNAME_RE = /^[A-Za-z0-9*?[\]][A-Za-z0-9.*?[\]_-]*$/
const SUDO_NETGROUP_RE = new RegExp(`^\\+${SUDO_NAME}$`)
const SUDO_ALIAS_RE = /^[A-Z][A-Z0-9_]*$/

const stripNegation = (v: string): string => (v.startsWith('!') ? v.slice(1).trimStart() : v)

function isNetwork(v: string): boolean {
  const [addr, mask, ...rest] = v.split('/')
  if (rest.length > 0 || addr === undefined) return false
  const v4 = isIpv4(addr)
  if (!v4 && !isIpv6(addr)) return false
  if (mask === undefined) return true
  if (/^\d+$/.test(mask)) return Number(mask) <= (v4 ? 32 : 128)
  return v4 && isIpv4(mask)
}

function isSudoHost(v: string): boolean {
  const host = stripNegation(v)
  return (
    host === 'ALL' || SUDO_HOSTNAME_RE.test(host) || SUDO_NETGROUP_RE.test(host) || isNetwork(host)
  )
}

function isSudoCommand(v: string): boolean {
  if (CONTROL_RE.test(v)) return false
  const command = stripNegation(v).trim()
  if (command === '') return false
  const head = command.split(/\s+/, 1)[0] ?? ''
  return SUDO_ALIAS_RE.test(command) || head === 'sudoedit' || head.startsWith('/')
}

// --- DNS --------------------------------------------------------------------

const DNS_LABEL = '[A-Za-z0-9_](?:[A-Za-z0-9_-]*[A-Za-z0-9_])?'
const DNS_HOST_RE = new RegExp(`^(?:\\*\\.)?${DNS_LABEL}(?:\\.${DNS_LABEL})*\\.?$`)
const DNS_MAIL_RE = /^(?:[^\s.\\]|\\\.)+(?:\.(?:[^\s.\\]|\\\.)+)*\.?$/
const DNS_WORD = '(?:"[^"]*"|\\S+)'

const isDnsHost = (v: string): boolean => v === '.' || DNS_HOST_RE.test(v)
const isUint = (v: string, max: number): boolean => /^\d+$/.test(v) && Number(v) <= max
const words = (v: string): string[] => v.trim().split(/\s+/)

function isPrefHost(v: string): boolean {
  const [pref, host, ...rest] = words(v)
  return rest.length === 0 && pref !== undefined && host !== undefined && isUint(pref, 65535) && isDnsHost(host)
}

function isSrv(v: string): boolean {
  const parts = words(v)
  return (
    parts.length === 4 &&
    parts.slice(0, 3).every((p) => isUint(p, 65535)) &&
    isDnsHost(parts[3] ?? '')
  )
}

function normalizeMailbox(v: string): string {
  const text = v.trim()
  const at = text.lastIndexOf('@')
  if (at < 0) return text
  return `${text.slice(0, at).replaceAll('.', '\\.')}.${text.slice(at + 1)}`
}

const dnsRegex = (pattern: string) => {
  const re = new RegExp(`^${pattern}$`)
  return (v: string): boolean => re.test(v.trim())
}

const FORMATS: Record<string, (v: string) => boolean> = {
  ssh_key: isSshKey,
  ip: isIp,
  ipv4: isIpv4,
  ipv6: isIpv6,
  mac: (v) => MAC_RE.test(v),
  host_or_ip: (v) => isIp(v) || matchesFormat('hostname', v),
  sid: (v) => SID_RE.test(v),
  rdn_value: (v) => v === v.trim() && !CONTROL_RE.test(v),
  sudo_user: (v) => SUDO_USER_RE.test(stripNegation(v)),
  sudo_runas_group: (v) => SUDO_RUNAS_GROUP_RE.test(stripNegation(v)),
  sudo_host: isSudoHost,
  sudo_command: isSudoCommand,
  dns_host: isDnsHost,
  dns_mailbox: (v) => DNS_MAIL_RE.test(normalizeMailbox(v)),
  dns_pref_host: isPrefHost,
  dns_afsdb: isPrefHost,
  dns_srv: isSrv,
  dns_caa: dnsRegex(`\\d{1,3} [A-Za-z0-9]+ ${DNS_WORD}`),
  dns_sshfp: dnsRegex('\\d{1,3} \\d{1,3} [0-9A-Fa-f]+'),
  dns_naptr: dnsRegex('\\d{1,10} \\d{1,10} "[^"]*" "[^"]*" "[^"]*" \\S+'),
  dns_ds: dnsRegex('\\d{1,5} \\d{1,3} \\d{1,3} [0-9A-Fa-f]+'),
  dns_cert: dnsRegex('\\S+ \\d{1,5} \\S+ \\S+'),
  dns_hinfo: dnsRegex(`${DNS_WORD} ${DNS_WORD}`),
}

for (const [name, matches] of Object.entries(FORMATS)) {
  registerFormat(name, matches, `objectFormats.${name}`)
}

/** Names of the formats registered here (for tests and the locale parity check). */
export const OBJECT_FORMAT_NAMES = Object.keys(FORMATS)

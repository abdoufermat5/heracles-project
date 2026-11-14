import { afterAll, beforeAll } from 'vitest'
import type { AttributeDescriptor } from '@/api/types'
import i18n from '@/i18n'
import { matchesFormat } from './formats'
import { OBJECT_FORMAT_NAMES } from './objectFormats'
import { validateAttribute } from './validation'

function str(constraints: AttributeDescriptor['constraints'], extra: Partial<AttributeDescriptor> = {}): AttributeDescriptor {
  return { name: 'x', label: 'X', kind: 'string', constraints, ...extra }
}

const errorOf = (a: AttributeDescriptor, v: unknown): string | undefined => validateAttribute(a, v)['']

describe('attribute format constraint', () => {
  it('refuses a value that does not match the named format, with the translated message', () => {
    const shell = str({ format: 'abs_path' })
    expect(errorOf(shell, 'bash')).toBe('Enter an absolute path, such as /bin/bash')
    expect(errorOf(shell, '/bin/bash')).toBeUndefined()
  })

  it('refuses an SSH key that is not a key line', () => {
    const key = str({ format: 'ssh_key' })
    expect(errorOf(key, 'hello')).toMatch(/OpenSSH public key/)
    expect(errorOf(key, 'ssh-rsa hello')).toMatch(/OpenSSH public key/)
    expect(
      errorOf(key, 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl me@host'),
    ).toBeUndefined()
  })

  it('checks every item of a list against the item format', () => {
    const list: AttributeDescriptor = {
      name: 'keys',
      label: 'Keys',
      kind: 'list',
      item: str({ format: 'sudo_host' }, { name: 'host' }),
    }
    const found = validateAttribute(list, ['ALL', '!!bad host', '10.0.0.0/8'])
    expect(Object.keys(found)).toEqual(['1'])
  })

  it('matches the whole value against a pattern, as the server does', () => {
    const login = str({ pattern: '[a-z]+' })
    expect(errorOf(login, 'abc')).toBeUndefined()
    expect(errorOf(login, 'abc def')).toBe('Invalid format')
  })

  it('follows the format selected by a sibling sub-field', () => {
    const record: AttributeDescriptor = {
      name: 'record',
      label: 'Record',
      kind: 'composite',
      fields: [
        { name: 'type', label: 'Type', kind: 'select', options: [{ value: 'A', label: 'A' }, { value: 'MX', label: 'MX' }] },
        {
          name: 'value',
          label: 'Value',
          kind: 'string',
          constraints: { format_by: { field: 'type', formats: { A: 'ipv4', MX: 'dns_pref_host' } } },
        },
      ],
    }
    expect(validateAttribute(record, { type: 'A', value: ' 192.0.2.1 ' })).toEqual({})
    expect(validateAttribute(record, { type: 'A', value: 'mail.example.com' })).toHaveProperty('value')
    expect(validateAttribute(record, { type: 'MX', value: '10 mail.example.com.' })).toEqual({})
    expect(validateAttribute(record, { type: 'MX', value: 'mail.example.com' })).toHaveProperty('value')
  })

  it('accepts an email without a dot in the domain, like the server', () => {
    const mail: AttributeDescriptor = { name: 'mail', label: 'Mail', kind: 'email' }
    expect(errorOf(mail, 'root@localhost')).toBeUndefined()
    expect(errorOf(mail, 'root')).toBe('Enter a valid email address')
  })
})

describe('object formats mirror the server', () => {
  const cases: Array<[string, string[], string[]]> = [
    ['ip', ['192.168.1.10', '::1', '2001:db8::1', '::ffff:192.0.2.1'], ['1.2.3', '256.1.1.1', '01.2.3.4', 'fe80::1%eth0', '1:2:3:4:5:6:7:8:9', ':::']],
    ['ipv4', ['10.0.0.1'], ['::1', '10.0.0']],
    ['ipv6', ['2001:db8::1', '1:2:3:4:5:6:7:8'], ['10.0.0.1', '1::2::3']],
    ['mac', ['aa:bb:cc:dd:ee:ff', 'AA-BB-CC-DD-EE-FF', 'aabbccddeeff'], ['aa:bb:cc', 'gg:bb:cc:dd:ee:ff']],
    ['host_or_ip', ['bmc.example.com', '10.1.1.1', '2001:db8::5'], ['not a host']],
    ['sid', ['S-1-5-21-1-2-3'], ['S-2-5', 'S-1-5']],
    ['rdn_value', ['Alice B'], [' Alice', 'Alice ', 'a\nb']],
    ['sudo_user', ['alice', '%wheel', '%#100', '#1000', '+admins', 'ALL', '!bob'], ['has space', '%']],
    ['sudo_runas_group', ['ALL', 'staff', '#10'], ['%staff']],
    ['sudo_host', ['ALL', 'web*', '10.0.0.0/8', '192.168.0.0/255.255.255.0', '+lan', '!db1'], ['10.0.0.0/33', '<>']],
    ['sudo_command', ['ALL', '/bin/ls -l', 'sudoedit /etc/hosts', 'SERVICES', '!/bin/su'], ['ls', '/bin/ls\nALL']],
    ['dns_host', ['ns1.example.com.', '_srv.example.com', '.'], ['bad host']],
    ['dns_mailbox', ['hostmaster.example.com.', 'admin@example.com'], ['with space.example.com']],
    ['dns_srv', ['10 5 5060 sip.example.com.'], ['10 5 sip.example.com']],
    ['dns_caa', ['0 issue "letsencrypt.org"'], ['issue letsencrypt.org']],
  ]
  it.each(cases)('%s', (name, good, bad) => {
    for (const v of good) expect(matchesFormat(name, v), `${name} accepts ${v}`).toBe(true)
    for (const v of bad) expect(matchesFormat(name, v), `${name} refuses ${v}`).toBe(false)
  })

  it('has an English and a French message for every format', async () => {
    await i18n.changeLanguage('fr')
    try {
      for (const name of OBJECT_FORMAT_NAMES) {
        for (const lng of ['en', 'fr']) {
          expect(i18n.exists(`objectFormats.${name}`, { lng }), `${lng} ${name}`).toBe(true)
        }
      }
    } finally {
      await i18n.changeLanguage('en')
    }
  })
})

describe('translated messages', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('fr')
  })
  afterAll(async () => {
    await i18n.changeLanguage('en')
  })

  it('shows the French message of a registered format', () => {
    expect(errorOf(str({ format: 'mac' }), 'nope')).toBe('Saisissez une adresse MAC, par exemple aa:bb:cc:dd:ee:ff')
  })
})

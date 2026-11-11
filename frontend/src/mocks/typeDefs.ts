import type { AttributeDescriptor, TypeDescriptor, TypeSummary } from '@/api/types'

const UID_RE = '^[a-z][a-z0-9._-]*$'

const str = (
  name: string,
  label: string,
  extra: Partial<AttributeDescriptor> = {},
): AttributeDescriptor => ({ name, label, kind: 'string', ...extra })

const languages = [
  { value: 'en', label: 'English' },
  { value: 'fr', label: 'Français' },
  { value: 'de', label: 'Deutsch' },
  { value: 'es', label: 'Español' },
]

export const typeDescriptors: TypeDescriptor[] = [
  {
    name: 'user',
    label: 'User',
    icon: 'user',
    category: 'directory',
    main_attr: 'uid',
    name_attr: 'cn',
    columns: [
      { key: 'uid', label: 'Login' },
      { key: 'cn', label: 'Name' },
      { key: 'mail', label: 'Email' },
      { key: 'employeeType', label: 'Type' },
    ],
    tabs: [
      {
        name: 'main',
        label: 'User',
        optional: false,
        sections: [
          {
            name: 'identity',
            label: 'Identity',
            attributes: [
              str('givenName', 'First name', {
                required: true,
                constraints: { max_length: 64 },
              }),
              str('sn', 'Last name', { required: true, constraints: { max_length: 64 } }),
              { name: 'cn', label: 'Common name', kind: 'display' },
              {
                name: 'jpegPhoto',
                label: 'Picture',
                kind: 'image',
                image: { max_width: 200, max_height: 200 },
              },
              {
                name: 'hrcDateOfBirth',
                label: 'Date of birth',
                kind: 'date',
              },
              {
                name: 'preferredLanguage',
                label: 'Language',
                kind: 'select',
                options: languages,
                default: 'en',
              },
            ],
          },
          {
            name: 'account',
            label: 'Account',
            attributes: [
              { name: 'base', label: 'Department', kind: 'department', required: true },
              str('uid', 'Login', {
                required: true,
                description: 'Lowercase letters, digits, dot, dash and underscore.',
                constraints: { pattern: UID_RE, min_length: 2, max_length: 32 },
              }),
              {
                name: 'userPassword',
                label: 'Password',
                kind: 'password',
                constraints: { min_length: 8 },
              },
              { name: 'forcePasswordChange', label: 'Require password change', kind: 'boolean' },
              { name: 'passwordExpiry', label: 'Password expires', kind: 'datetime' },
              {
                name: 'employeeType',
                label: 'Employee type',
                kind: 'select',
                options: [
                  { value: 'employee', label: 'Employee' },
                  { value: 'contractor', label: 'Contractor' },
                  { value: 'intern', label: 'Intern' },
                ],
                default: 'employee',
              },
              { name: 'internalId', label: 'Internal id', kind: 'hidden' },
            ],
          },
          {
            name: 'contact',
            label: 'Contact',
            attributes: [
              { name: 'mail', label: 'Email', kind: 'email', required: true },
              {
                name: 'telephoneNumber',
                label: 'Phone numbers',
                kind: 'phone',
                multivalued: true,
              },
              { name: 'postalAddress', label: 'Postal address', kind: 'postal_address' },
              { name: 'labeledURI', label: 'Website', kind: 'url' },
              { name: 'manager', label: 'Manager', kind: 'object_ref', ref_type: 'user' },
              {
                name: 'userCertificate',
                label: 'Certificate',
                kind: 'file',
              },
              {
                name: 'description',
                label: 'Notes',
                kind: 'text',
                constraints: { max_length: 500 },
              },
            ],
          },
        ],
      },
      {
        name: 'posix',
        label: 'POSIX account',
        optional: true,
        description: 'Unix account: UID, home directory, shell',
        sections: [
          {
            name: 'posix',
            label: 'Unix account',
            attributes: [
              { name: 'uidNumber', label: 'User id', kind: 'int', required: true, constraints: { min: 1000, max: 65000 } },
              { name: 'gidNumber', label: 'Group id', kind: 'int', required: true, constraints: { min: 1000, max: 65000 } },
              str('homeDirectory', 'Home directory', {
                required: true,
                constraints: { pattern: '^/.*$' },
              }),
              {
                name: 'loginShell',
                label: 'Login shell',
                kind: 'select',
                options: [
                  { value: '/bin/bash', label: 'bash' },
                  { value: '/bin/zsh', label: 'zsh' },
                  { value: '/usr/sbin/nologin', label: 'nologin' },
                ],
                default: '/bin/bash',
              },
              { name: 'diskQuotaGb', label: 'Disk quota (GB)', kind: 'float', constraints: { min: 0, max: 1000 } },
              {
                name: 'groups',
                label: 'Supplementary groups',
                kind: 'multiselect',
                options: [
                  { value: 'staff', label: 'staff' },
                  { value: 'docker', label: 'docker' },
                  { value: 'dialout', label: 'dialout' },
                  { value: 'sudo', label: 'sudo' },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
  {
    name: 'group',
    label: 'Group',
    icon: 'users',
    category: 'directory',
    main_attr: 'cn',
    name_attr: 'cn',
    columns: [
      { key: 'cn', label: 'Name' },
      { key: 'description', label: 'Description' },
    ],
    tabs: [
      {
        name: 'main',
        label: 'Group',
        optional: false,
        sections: [
          {
            name: 'general',
            label: 'General',
            attributes: [
              { name: 'base', label: 'Department', kind: 'department', required: true },
              str('cn', 'Name', { required: true, constraints: { pattern: UID_RE } }),
              { name: 'description', label: 'Description', kind: 'text' },
            ],
          },
          {
            name: 'members',
            label: 'Members',
            attributes: [
              {
                name: 'member',
                label: 'Members',
                kind: 'object_ref',
                ref_type: 'user',
                multivalued: true,
              },
            ],
          },
        ],
      },
    ],
  },
  {
    name: 'role',
    label: 'Role',
    icon: 'shield',
    category: 'access',
    main_attr: 'cn',
    name_attr: 'cn',
    columns: [
      { key: 'cn', label: 'Name' },
      { key: 'description', label: 'Description' },
    ],
    tabs: [
      {
        name: 'main',
        label: 'Role',
        optional: false,
        sections: [
          {
            name: 'general',
            label: 'General',
            attributes: [
              { name: 'base', label: 'Department', kind: 'department', required: true },
              str('cn', 'Name', { required: true }),
              { name: 'description', label: 'Description', kind: 'text' },
              {
                name: 'roleOccupant',
                label: 'Occupants',
                kind: 'object_ref',
                ref_type: 'user',
                multivalued: true,
              },
            ],
          },
        ],
      },
    ],
  },
  {
    name: 'department',
    label: 'Department',
    icon: 'building-2',
    category: 'directory',
    main_attr: 'ou',
    name_attr: 'ou',
    columns: [
      { key: 'ou', label: 'Name' },
      { key: 'description', label: 'Description' },
    ],
    tabs: [
      {
        name: 'main',
        label: 'Department',
        optional: false,
        sections: [
          {
            name: 'general',
            label: 'General',
            attributes: [
              { name: 'base', label: 'Parent department', kind: 'department', required: true },
              str('ou', 'Name', { required: true }),
              { name: 'description', label: 'Description', kind: 'text' },
            ],
          },
        ],
      },
    ],
  },
  {
    name: 'dns_zone',
    label: 'DNS zone',
    icon: 'globe',
    category: 'network',
    main_attr: 'zoneName',
    name_attr: 'zoneName',
    columns: [
      { key: 'zoneName', label: 'Zone' },
      { key: 'serial', label: 'Serial' },
      { key: 'description', label: 'Description' },
    ],
    tabs: [
      {
        name: 'main',
        label: 'Zone',
        optional: false,
        sections: [
          {
            name: 'general',
            label: 'General',
            attributes: [
              { name: 'base', label: 'Department', kind: 'department', required: true },
              str('zoneName', 'Zone name', {
                required: true,
                constraints: { pattern: '^([a-z0-9-]+\\.)+[a-z]{2,}$' },
              }),
              { name: 'serial', label: 'Serial', kind: 'display' },
              { name: 'description', label: 'Description', kind: 'text' },
            ],
          },
          {
            name: 'soa',
            label: 'Start of authority',
            attributes: [
              {
                name: 'soa',
                label: 'SOA record',
                kind: 'composite',
                required: true,
                fields: [
                  str('primaryNs', 'Primary name server', { required: true }),
                  { name: 'adminEmail', label: 'Admin email', kind: 'email', required: true },
                  { name: 'refresh', label: 'Refresh (s)', kind: 'int', default: 3600, constraints: { min: 60 } },
                  { name: 'retry', label: 'Retry (s)', kind: 'int', default: 600, constraints: { min: 60 } },
                  { name: 'expire', label: 'Expire (s)', kind: 'int', default: 1209600 },
                  { name: 'minimum', label: 'Minimum TTL (s)', kind: 'int', default: 300 },
                ],
              },
              {
                name: 'nameservers',
                label: 'Name servers',
                kind: 'list',
                item: str('ns', 'Name server'),
              },
            ],
          },
          {
            name: 'records',
            label: 'Records',
            attributes: [
              {
                name: 'records',
                label: 'Resource records',
                kind: 'list',
                item: {
                  name: 'record',
                  label: 'Record',
                  kind: 'composite',
                  fields: [
                    str('name', 'Name', { required: true }),
                    {
                      name: 'type',
                      label: 'Type',
                      kind: 'select',
                      required: true,
                      default: 'A',
                      options: ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS'].map((v) => ({
                        value: v,
                        label: v,
                      })),
                    },
                    { name: 'ttl', label: 'TTL', kind: 'int', default: 3600 },
                    str('value', 'Value', { required: true }),
                  ],
                },
              },
            ],
          },
        ],
      },
    ],
  },
]

export const typeSummaries: TypeSummary[] = [
  { name: 'user', label: 'User', label_plural: 'Users', icon: 'user', category: 'directory', can_create: true },
  { name: 'group', label: 'Group', label_plural: 'Groups', icon: 'users', category: 'directory', can_create: true },
  { name: 'department', label: 'Department', label_plural: 'Departments', icon: 'building-2', category: 'directory', can_create: true },
  { name: 'role', label: 'Role', label_plural: 'Roles', icon: 'shield', category: 'access', can_create: true },
  { name: 'dns_zone', label: 'DNS zone', label_plural: 'DNS zones', icon: 'globe', category: 'network', can_create: true },
]

/** RDN container (relative to a department) per type. */
export const typeRdn: Record<string, string> = {
  user: 'ou=people',
  group: 'ou=groups',
  role: 'ou=roles',
  dns_zone: 'ou=dns',
  department: '',
}

/** Strings of the active-sessions panel and the code-based re-authentication. French: locale-fr.ts. */
export const meEn = {
  reauth: {
    useCode: 'Use a code from my authenticator app instead',
    usePassword: 'Use my password instead',
    code: 'Authenticator or recovery code',
    passwordChangeBody: 'For your security, enter your password again before changing it.',
    adminBody: 'For your security, confirm your identity before signing this person out.',
  },
  sessions: {
    title: 'Where you are signed in',
    help: 'Devices and browsers with an open session on your account. Sign out the ones you do not recognise.',
    current: 'This device',
    unknownDevice: 'Unknown device',
    created: 'Signed in {{when}}',
    lastSeen: 'last active {{when}}',
    revoke: 'Sign out {{name}}',
    revokeOthers: 'Sign out all other devices',
    revoked_one: '{{count}} device signed out.',
    revoked_other: '{{count}} devices signed out.',
    none: 'No other session is open.',
    failed: 'Could not update your sessions.',
    admin: {
      title: 'Sign {{name}} out everywhere?',
      body: 'Every open session of this account ends immediately. The person can sign in again.',
      confirm: 'Sign out everywhere',
      cancel: 'Cancel',
      done_one: '{{count}} session ended.',
      done_other: '{{count}} sessions ended.',
    },
  },
}

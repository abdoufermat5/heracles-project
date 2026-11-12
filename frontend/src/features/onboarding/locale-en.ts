/** Strings of the first-login checklist and the "next step" buttons of empty pages. */
export const onboardingEn = {
  onboarding: {
    title: 'Get started',
    progress: '{{done}} of {{total}} done',
    dismiss: 'Dismiss',
    dismissLabel: 'Dismiss the getting started checklist',
    markDone: 'Mark “{{item}}” as done',
    done: 'Done',
    items: {
      secondFactor: {
        title: 'Enrol a second factor',
        help: 'Protect your own account with an authenticator app or a security key.',
      },
      health: {
        title: 'Check that the health checks pass',
        help: 'Make sure the directory, schema and settings are in order.',
        failing: '{{count}} to look at',
      },
      access: {
        title: 'Review roles and access',
        help: 'See who can do what, and adjust the roles to your organisation.',
      },
      plugins: {
        title: 'Review the plugins',
        help: 'Switch on what you manage, switch off what you do not.',
      },
      import: {
        title: 'Import your users',
        help: 'Create many accounts at once from a CSV or LDIF file.',
      },
    },
    open: 'Open',
    next: {
      plugins: 'Open plugins',
      health: 'Open health checks',
      people: 'Browse people',
      dashboard: 'Back to the dashboard',
    },
  },
}

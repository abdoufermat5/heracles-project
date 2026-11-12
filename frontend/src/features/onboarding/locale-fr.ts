/** French strings of the first-login checklist; mirrors locale-en.ts. */
export const onboardingFr = {
  onboarding: {
    title: 'Pour commencer',
    progress: '{{done}} sur {{total}} terminées',
    dismiss: 'Masquer',
    dismissLabel: 'Masquer la liste de démarrage',
    markDone: 'Marquer « {{item}} » comme terminé',
    done: 'Terminé',
    items: {
      secondFactor: {
        title: 'Activer un second facteur',
        help: 'Protégez votre propre compte avec une application d’authentification ou une clé de sécurité.',
      },
      health: {
        title: 'Vérifier que les contrôles de santé passent',
        help: 'Assurez-vous que l’annuaire, le schéma et les réglages sont en ordre.',
        failing: '{{count}} à examiner',
      },
      access: {
        title: 'Passer en revue les rôles et les accès',
        help: 'Voyez qui peut faire quoi et ajustez les rôles à votre organisation.',
      },
      plugins: {
        title: 'Passer en revue les modules',
        help: 'Activez ce que vous gérez, désactivez le reste.',
      },
      import: {
        title: 'Importer vos utilisateurs',
        help: 'Créez de nombreux comptes d’un coup à partir d’un fichier CSV ou LDIF.',
      },
    },
    open: 'Ouvrir',
    next: {
      plugins: 'Ouvrir les modules',
      health: 'Ouvrir les contrôles de santé',
      people: 'Parcourir les personnes',
      dashboard: 'Retour au tableau de bord',
    },
  },
}

/** Textes du panneau des sessions actives et de la reconfirmation par code. Miroir de locale-en.ts. */
export const meFr = {
  reauth: {
    useCode: 'Utiliser plutôt un code de mon application d’authentification',
    usePassword: 'Utiliser plutôt mon mot de passe',
    code: 'Code de l’application ou code de secours',
    passwordChangeBody: 'Par sécurité, saisissez à nouveau votre mot de passe avant de le modifier.',
    adminBody: 'Par sécurité, confirmez votre identité avant de déconnecter cette personne.',
  },
  sessions: {
    title: 'Où vous êtes connecté',
    help: 'Appareils et navigateurs ayant une session ouverte sur votre compte. Déconnectez ceux que vous ne reconnaissez pas.',
    current: 'Cet appareil',
    unknownDevice: 'Appareil inconnu',
    created: 'Connecté {{when}}',
    lastSeen: 'dernière activité {{when}}',
    revoke: 'Déconnecter {{name}}',
    revokeOthers: 'Déconnecter tous les autres appareils',
    revoked_one: '{{count}} appareil déconnecté.',
    revoked_other: '{{count}} appareils déconnectés.',
    none: 'Aucune autre session n’est ouverte.',
    failed: 'Impossible de mettre à jour vos sessions.',
    admin: {
      title: 'Déconnecter {{name}} partout ?',
      body: 'Toutes les sessions ouvertes de ce compte se terminent immédiatement. La personne pourra se reconnecter.',
      confirm: 'Déconnecter partout',
      cancel: 'Annuler',
      done_one: '{{count}} session terminée.',
      done_other: '{{count}} sessions terminées.',
    },
  },
}

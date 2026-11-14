import type { shellEn } from './shell'

export const shellFr: typeof shellEn = {
  shellUI: {
    shortcuts: {
      title: 'Raccourcis clavier',
      description: 'Tapez la séquence de touches hors de tout champ. La casse est sans importance.',
      open: 'Afficher les raccourcis clavier',
      empty: 'Aucun raccourci enregistré.',
      scopes: {
        global: 'Partout',
        navigation: 'Aller à',
        page: 'Cette page',
      },
      palette: 'Ouvrir la palette de commandes',
      search: 'Placer le curseur dans la recherche de la page',
      sheet: 'Afficher cette liste',
      goDashboard: 'Tableau de bord',
      goUsers: 'Utilisateurs',
      goGroups: 'Groupes',
      goRoles: 'Contrôle d’accès',
      goAudit: "Journal d'audit",
      goConfig: 'Paramètres',
      goHealth: 'Santé',
      goTasks: 'Tâches',
    },
    palette: {
      newUser: 'Nouvel utilisateur',
      newGroup: 'Nouveau groupe',
      checkRights: 'Vérifier les droits…',
      auditFor: "Ouvrir le journal d'audit de {{label}}",
      switchTheme: 'Changer de thème',
      switchLanguage: 'Changer de langue',
      signOut: 'Se déconnecter',
      copyDn: "Copier le DN de l'objet courant",
      copied: 'DN copié',
      copyFailed: 'Impossible de copier le DN',
      recent: 'Récents',
      objects: 'Objets',
    },
    lock: {
      failed: "La modification du compte n'a pas été appliquée.",
    },
  },
}

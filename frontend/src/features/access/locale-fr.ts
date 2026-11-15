import type { grantsEn } from './locale-en'

/** French strings of the access screens, typed against the English ones. */
export const grantsFr: typeof grantsEn = {
  grants: {
    until: 'Jusqu’au {{day}}',
    untilColumn: 'Fin de l’accès',
    permanent: 'Sans date de fin',
    endDate: {
      open: 'Définir la date de fin pour {{name}}',
      title: 'Date de fin pour {{name}}',
      description: 'L’appartenance est retirée automatiquement après ce jour (UTC).',
      label: 'Dernier jour d’accès',
      hint: 'Pour une appartenance permanente, utilisez « Retirer la date de fin ».',
      required: 'Choisissez un jour',
      save: 'Enregistrer',
      cancel: 'Annuler',
      clear: 'Retirer la date de fin',
      saved: 'L’accès prend fin après le {{day}}',
      cleared: 'L’appartenance est de nouveau permanente',
      failed: 'La date de fin n’a pas pu être enregistrée',
    },
  },
}

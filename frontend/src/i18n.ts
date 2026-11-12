import i18n, { type BackendModule, type ResourceKey } from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'
import en from './locales/en'

/**
 * English is the fallback and stays in the entry bundle; every other language is a
 * separate chunk fetched on demand. i18next waits for `read` before it announces a
 * language change, so `changeLanguage('fr')` resolves once the French strings are in.
 */
const lazyLanguages: Record<string, () => Promise<{ default: ResourceKey }>> = {
  fr: () => import('./locales/fr'),
}

const lazyBackend: BackendModule = {
  type: 'backend',
  callbackApi: false,
  init() {},
  // Regional variants (fr-FR) resolve to their base language bundle, which is loaded on its own.
  async read(language) {
    const load = lazyLanguages[language]
    return load ? (await load()).default : null
  },
}

/**
 * Settles once the detected language is usable. A failed chunk load leaves the app on the
 * English fallback rather than blocking the first render.
 */
export const i18nReady: Promise<void> = i18n
  .use(LanguageDetector)
  .use(lazyBackend)
  .use(initReactI18next)
  .init({
    resources: { en: { translation: en } },
    partialBundledLanguages: true,
    fallbackLng: 'en',
    supportedLngs: ['en', 'fr'],
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false },
    detection: { order: ['localStorage', 'navigator'], lookupLocalStorage: 'heracles.lang', caches: ['localStorage'] },
  })
  .then(
    () => undefined,
    () => undefined,
  )

/**
 * `{{label, lcfirst}}`: a type label dropped into the middle of a sentence ("New user"),
 * leaving acronyms and proper names ("LDAP entry", "DNS zone") untouched.
 */
i18n.services.formatter?.add('lcfirst', (value: unknown) => {
  const s = String(value ?? '')
  return /^[A-ZÀ-Ý]{2}/.test(s) ? s : s.charAt(0).toLocaleLowerCase() + s.slice(1)
})

i18n.on('languageChanged', (lng) => {
  document.documentElement.lang = lng.startsWith('fr') ? 'fr' : 'en'
})

export default i18n

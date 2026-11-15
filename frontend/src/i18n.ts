import i18n, { type BackendModule, type LanguageDetectorModule, type ResourceKey } from 'i18next'
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

const LANG_KEY = 'heracles.lang'

/** The language picked earlier on this browser, else the browser's preferred languages. */
const detector: LanguageDetectorModule = {
  type: 'languageDetector',
  init() {},
  detect() {
    try {
      const saved = localStorage.getItem(LANG_KEY)
      if (saved) return saved
    } catch {
      // storage blocked: fall through to the browser languages
    }
    return navigator.languages.length > 0 ? [...navigator.languages] : navigator.language
  },
  cacheUserLanguage(language) {
    try {
      localStorage.setItem(LANG_KEY, language)
    } catch {
      // storage blocked: the choice lasts for this page only
    }
  },
}

/**
 * Settles once the detected language is usable. A failed chunk load leaves the app on the
 * English fallback rather than blocking the first render.
 */
export const i18nReady: Promise<void> = i18n
  .use(detector)
  .use(lazyBackend)
  .use(initReactI18next)
  .init({
    resources: { en: { translation: en } },
    partialBundledLanguages: true,
    fallbackLng: 'en',
    supportedLngs: ['en', 'fr'],
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false },
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

/**
 * Adds the English strings of the settings screens when a page that uses them loads, which
 * keeps them out of the entry chunk. Every module that reads a `settingsUI.*` key imports this
 * file; French has them already (the whole French bundle loads at once, see i18n.ts).
 */
import i18n from '@/i18n'
import { settingsEn } from './settings'

i18n.addResourceBundle('en', 'translation', settingsEn, true, false)

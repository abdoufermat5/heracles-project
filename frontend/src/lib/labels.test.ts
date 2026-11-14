import { beforeAll, afterAll } from 'vitest'
import i18n from '@/i18n'
import { attributeLabel, localText, typeLabel, typeLabelPlural } from './labels'

describe('label layer', () => {
  // French is a separate chunk: load it once so the fixed translators have it.
  beforeAll(async () => {
    await i18n.changeLanguage('fr')
  })
  afterAll(async () => {
    await i18n.changeLanguage('en')
  })

  it('resolves a known type by its stable id in both languages', () => {
    const en = i18n.getFixedT('en')
    const fr = i18n.getFixedT('fr')
    const user = { name: 'user', label: 'User', label_plural: 'Users' }
    expect(typeLabel(en, user)).toBe('User')
    expect(typeLabelPlural(en, user)).toBe('Users')
    expect(typeLabel(fr, user)).toBe('Utilisateur')
    expect(typeLabelPlural(fr, user)).toBe('Utilisateurs')
  })

  it('keeps the server label of a type the catalogue does not know, in both languages', () => {
    const plugin = { name: 'vendor_widget', label: 'Phone macro', label_plural: 'Phone macros' }
    for (const lng of ['en', 'fr']) {
      const t = i18n.getFixedT(lng)
      expect(typeLabel(t, plugin)).toBe('Phone macro')
      expect(typeLabelPlural(t, plugin)).toBe('Phone macros')
    }
  })

  it('keeps the server label of an attribute the catalogue does not know', () => {
    const fr = i18n.getFixedT('fr')
    expect(attributeLabel(fr, 'cn', 'Name')).toBe('Nom')
    expect(attributeLabel(fr, 'pluginAttribute', 'Plugin label')).toBe('Plugin label')
  })

  it('translates a descriptor text by its stable key, whatever the wording', () => {
    const fr = i18n.getFixedT('fr')
    expect(attributeLabel(fr, 'sn', 'Last name', 'type/user/attr/sn')).toBe('Nom de famille')
    // Renaming the English label on the server does not drop the translation.
    expect(attributeLabel(fr, 'sn', 'Surname', 'type/user/attr/sn')).toBe('Nom de famille')
    expect(localText(fr, 'type/user/tab/main/section/identity', 'Identity')).toBe('Identité')
    expect(localText(fr, 'type/user/tab/main/section/identity', 'Who is this?')).toBe('Identité')
  })

  it('shows the server wording for a key the catalogue does not know', () => {
    const fr = i18n.getFixedT('fr')
    expect(localText(fr, 'type/vendor_widget/attr/x', 'Widget')).toBe('Widget')
    expect(
      attributeLabel(fr, 'vendorAttribute', 'Widget', 'type/vendor_widget/attr/vendorAttribute'),
    ).toBe('Widget')
  })

  it('shows a payload text that has no key as sent', () => {
    expect(localText(i18n.getFixedT('fr'), 'Configuration')).toBe('Configuration')
  })
})

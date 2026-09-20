import test from 'node:test'
import assert from 'node:assert/strict'
import { createI18n } from 'vue-i18n'
import catalog from './emoji/catalog.ts'
import en from './emoji/messages.en.ts'
import fr from './emoji/messages.fr.ts'
import zh from './emoji/messages.zh.ts'
import mdi from './emoji/mdi.ts'
import awesome from './emoji/awesome.ts'
import { normalizedTagIcon, unicodeIcon } from './tagIcon.ts'

test('Unicode emoji use text and saved SVG emoji references remain displayable', () => {
  assert.match(unicodeIcon('emoji:1F680'), /🚀/u)
  assert.match(unicodeIcon(normalizedTagIcon('/tag-icons/openmoji/1F680.svg')), /🚀/u)
  assert.match(unicodeIcon(normalizedTagIcon('/tag-icons/fluent/1F680.svg')), /🚀/u)
  assert.equal(unicodeIcon(normalizedTagIcon('/tag-icons/openmoji/2764-FE0F.svg')), '❤️')
  assert.equal(unicodeIcon('emoji:110000'), '')
})

test('complete Unicode and font catalogues have usable names and search terms in every language', () => {
  assert.ok(catalog.icons.filter(icon => icon.tone === 0).length > 1500)
  assert.ok(mdi.icons.length > 7000)
  assert.ok(awesome.icons.length > 2000)
  for (const library of [{ ...catalog, messages: { en, fr, zh } }, mdi, awesome]) {
    assert.equal(new Set(library.icons.map(icon => icon.code)).size, library.icons.length)
    for (const [locale, messages] of Object.entries(library.messages)) {
      const i18n = createI18n({ legacy: false, locale, messages: { [locale]: messages } })
      const errors = []
      i18n.global.setMissingHandler((_locale, key) => { errors.push(key) })
      assert.deepEqual(Object.keys(messages.documentTagEmoji).sort(), library.icons.map(icon => icon.code).sort())
      for (const icon of library.icons) {
        for (const field of ['name', 'keywords']) {
          const key = `documentTagEmoji.${icon.code}.${field}`
          const value = i18n.global.t(key)
          assert.ok(value && value !== key, `${locale}: ${key}`)
        }
      }
      assert.deepEqual(errors, [])
      i18n.dispose()
    }
  }
})

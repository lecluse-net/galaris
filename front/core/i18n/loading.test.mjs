import assert from 'node:assert/strict'
import test from 'node:test'
import { createI18n } from 'vue-i18n'
import { loadTypescript, deferred } from '../../test-support/load-typescript.mjs'

function setup(browser = 'en-US') {
  const french = deferred()
  const chinese = deferred()
  const reads = { fr: 0, zh: 0 }
  let frenchFailure = false
  const attributes = {}
  const quasar = []
  const state = loadTypescript(new URL('./index.ts', import.meta.url), {
    'vue-i18n': { createI18n },
    quasar: { Lang: { set: locale => quasar.push(locale) } },
    'quasar/lang/en-US': { __esModule: true, default: 'en' },
    'quasar/lang/fr': { __esModule: true, default: 'fr' },
    'quasar/lang/zh-CN': { __esModule: true, default: 'zh' },
    './catalogs/en': { __esModule: true, default: { greeting: 'Hello', fallback: 'English fallback', count: '{count} items' } },
    'virtual:galaris-locale-fr': { __esModule: true, default: '/locale-fr.json' },
    'virtual:galaris-locale-zh': { __esModule: true, default: '/locale-zh.json' },
  }, {
    navigator: { language: browser },
    document: { documentElement: { setAttribute: (key, value) => { attributes[key] = value } } },
    async fetch(url) {
      const locale = url.includes('-fr.') ? 'fr' : 'zh'
      reads[locale] += 1
      if (locale === 'fr' && frenchFailure) throw new Error('Synthetic catalog download failure')
      const messages = await (locale === 'fr' ? french : chinese).promise
      return { ok: true, json: async () => messages.default }
    },
  })
  return { ...state, french, chinese, reads, attributes, quasar,
    failFrench(value) { frenchFailure = value } }
}

test('only the selected language loads, once, before locale and platform hints change', async () => {
  const state = setup()
  await state.initialLocaleReady
  const first = state.setLocale('fr')
  const second = state.setLocale('fr')
  await Promise.resolve()
  assert.deepEqual(state.reads, { fr: 1, zh: 0 })
  assert.equal(state.getLocale(), 'en')
  assert.equal(state.attributes.lang, 'en')
  state.french.resolve({ default: { greeting: 'Bonjour', count: '{count} éléments' } })
  assert.equal(await first, false)
  assert.equal(await second, true)
  assert.equal(state.getLocale(), 'fr')
  assert.equal(state.attributes.lang, 'fr')
  assert.equal(state.quasar.at(-1), 'fr')
  assert.equal(state.i18n.global.t('greeting'), 'Bonjour')
  assert.equal(state.i18n.global.t('fallback'), 'English fallback')
  assert.equal(state.i18n.global.t('count', { count: 3 }), '3 éléments')
  await state.setLocale('en')
  await state.setLocale('fr')
  assert.deepEqual(state.reads, { fr: 1, zh: 0 })
})

test('a late language download or an expired session cannot replace the current choice', async () => {
  const state = setup()
  await state.initialLocaleReady
  const french = state.setLocale('fr')
  const chinese = state.setLocale('zh')
  state.chinese.resolve({ default: { greeting: '你好' } })
  assert.equal(await chinese, true)
  state.french.resolve({ default: { greeting: 'Bonjour' } })
  assert.equal(await french, false)
  assert.equal(state.getLocale(), 'zh')
  await state.setLocale('fr', () => false)
  assert.equal(state.getLocale(), 'zh')
})

test('a failed download keeps readable messages and can be retried', async () => {
  const state = setup()
  await state.initialLocaleReady
  state.failFrench(true)
  await assert.rejects(state.setLocale('fr'), /Synthetic catalog download failure/)
  assert.equal(state.i18n.global.t('greeting'), 'Hello')
  assert.equal(state.attributes.lang, 'en')
  state.failFrench(false)
  state.french.resolve({ default: { greeting: 'Bonjour' } })
  await state.setLocale('fr')
  assert.equal(state.i18n.global.t('greeting'), 'Bonjour')
  assert.equal(state.reads.fr, 2)
})

test('bootstrap waits for the browser locale and unsupported profile locales use that preference', async () => {
  const state = setup('fr-CA')
  state.french.resolve({ default: { greeting: 'Bonjour' } })
  await state.initialLocaleReady
  assert.equal(state.getLocale(), 'fr')
  await state.setLocale('en')
  await state.applyUserLocale('unsupported')
  assert.equal(state.getLocale(), 'fr')
  assert.equal(state.reads.zh, 0)
})

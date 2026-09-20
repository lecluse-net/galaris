import assert from 'node:assert/strict'
import test from 'node:test'
import { navigationSections } from './navigationSections.ts'
import harnessTranslations from '../harnesses/i18n.ts'
import paramsTranslations from '../../core/params/i18n.ts'

test('navigation declares the product lifecycle sections in order', () => {
  assert.deepEqual(navigationSections.map(section => section.rootKey), ['configure', 'act', 'knowledge', 'monitor', 'admin'])
  assert.equal(navigationSections[0].label, 'index.sidebar.configure')
})

test('Harness and Preferences labels retain their explicit product vocabulary', () => {
  assert.equal(harnessTranslations.fr.harnesses.catalog.navigationAdd, 'Ajout de harnais')
  assert.equal(harnessTranslations.en.harnesses.catalog.navigationAdd, 'Add Harness')
  assert.equal(paramsTranslations.fr.nav.params, 'Préférences')
  assert.equal(paramsTranslations.en.nav.params, 'Preferences')
})

import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { dataLoader, generatedNavigationFiles, navigationContext } from './navigation-context.mjs'

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'navigation-docs-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  function write(file, content) {
    const target = path.join(root, 'front', file)
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.writeFileSync(target, content)
  }
  for (const file of ['core/navigation/tree.ts', 'core/i18n/merge.ts']) {
    write(file, fs.readFileSync(new URL(`../${file}`, import.meta.url), 'utf8'))
  }
  write('modules.ts', "export const modules = ['core/params', 'bridge/sample']")
  write('app/index/navigationSections.ts', "export const navigationSections = [{rootKey: 'admin', label: 'admin'}]")
  write('core/i18n/locales/fr.ts', "export default {admin: 'Administration', prefs: 'Préférences', feature: 'Fonction'}")
  write('core/i18n/locales/en.ts', "export default {admin: 'Administration', prefs: 'Preferences', feature: 'Feature'}")
  write('core/params/navigation.ts', `export default {admin: {children: {params: {
    label: 'prefs', to: '/params', privileges: ['READ_SETTINGS'],
    visible: () => { throw new Error('Do not evaluate installation state') },
  }}}}`)
  write('bridge/sample/navigation.ts', `export default {admin: {children: {params: {children: {
    feature: { label: 'feature', to: '/sample', privileges: ['READ_SAMPLE', 'EDIT_SAMPLE'] },
  }}}}}`)
  write('app/inactive/navigation.ts', "export default {admin: {children: {inactive: {label: 'unknown', to: '/inactive'}}}}")
  return { root, write }
}

test('documentation composes activated menus and preserves ancestor visibility without evaluating it', t => {
  const { root } = fixture(t)
  const context = navigationContext(root)
  assert.deepEqual(context.entries.map(e => e.route), ['/params', '/sample'])
  const child = context.entries[1]
  assert.deepEqual(child.breadcrumbs.fr, ['Administration', 'Préférences', 'Fonction'])
  assert.deepEqual(child.breadcrumbs.en, ['Administration', 'Preferences', 'Feature'])
  assert.deepEqual(child.privilege_groups, [['READ_SETTINGS'], ['READ_SAMPLE', 'EDIT_SAMPLE']])
  assert.deepEqual(child.conditions, [{ node: 'admin.params', visibility: 'dynamic' }])
  assert.deepEqual(context.entries[0].sources, ['front/core/params/navigation.ts', 'front/bridge/sample/navigation.ts'])
  assert.deepEqual(generatedNavigationFiles(root), generatedNavigationFiles(root))
})

test('route and label changes propagate to both documentation languages; missing translations fail loudly', t => {
  const { root, write } = fixture(t)
  const before = generatedNavigationFiles(root)
  write('bridge/sample/navigation.ts', "export default {admin: {children: {feature: {label: 'feature', to: '/renamed'}}}}")
  write('bridge/sample/i18n.ts', "export default {fr: {feature: 'Nouveau libellé'}, en: {feature: 'New label'}}")
  const after = generatedNavigationFiles(root)
  for (const [file, content] of after) {
    assert.notEqual(content, before.get(file))
    assert.ok(content.includes('/renamed'))
  }
  assert.equal(navigationContext(root).entries[1].labels.fr, 'Nouveau libellé')
  write('bridge/sample/navigation.ts', "export default {admin: {children: {feature: {label: 'missing', to: '/renamed'}}}}")
  assert.throws(() => navigationContext(root), /Missing fr navigation label/)
})

test('the data loader rejects unreviewed runtime dependencies', t => {
  const { root, write } = fixture(t)
  write('bridge/sample/navigation.ts', "import { secret } from './services/client'; export default secret")
  assert.throws(() => navigationContext(root), /Unreviewed navigation import/)
  const load = dataLoader(path.join(root, 'front'))
  assert.throws(() => load('app/chat/availability.ts').isChatNavigationVisible(), /must not run/)
})

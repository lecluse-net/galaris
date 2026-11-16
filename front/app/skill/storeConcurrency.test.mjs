import * as vue from 'vue'
import assert from 'node:assert/strict'
import test from 'node:test'
import * as pinia from 'pinia'
import { deferred, loadTypescript } from '../../test-support/load-typescript.mjs'
import { sessionStoreScope } from '../../test-support/session-store.mjs'

function setup(service) {
  const { useSkillStore } = loadTypescript(new URL('./stores/skillStore.ts', import.meta.url), {
    vue, pinia, '@/core/api': { sessionGeneration: () => 'synthetic-session' },
    '@/core/util/facade': sessionStoreScope(), '../services/skillService': { skillService: service },
  })
  return useSkillStore(pinia.createPinia())
}

test('file contents always belong to the latest selected path, including binary selection and close', async () => {
  const reads = new Map()
  const store = setup({ getFileContent: (_id, path) => { const read = deferred(); reads.set(path, read); return read.promise } })
  store.currentSkill = { id: 1 }
  const first = store.openFile({ path: 'a.md', text: true }), second = store.openFile({ path: 'b.md', text: true })
  reads.get('b.md').resolve({ data: { content: 'Synthetic B' } }); await second
  reads.get('a.md').resolve({ data: { content: 'Synthetic A' } }); await first
  assert.equal(store.currentPath, 'b.md'); assert.equal(store.currentContent, 'Synthetic B')
  for (const close of [() => store.openFile({ path: 'binary.png', text: false }), () => store.clearCurrent()]) {
    const pending = store.openFile({ path: 'pending.md', text: true })
    await close()
    reads.get('pending.md').resolve({ data: { content: 'Obsolete content' } }); await pending
    assert.equal(store.currentContent, ''); assert.equal(store.contentLoading, false)
  }
  store.$dispose()
})

test('opening another skill discards the old file list and content as one selection', async () => {
  const old = deferred(), current = deferred()
  const store = setup({ getFiles: async () => ({ data: [{ path: 'SKILL.md', text: true }] }),
    getFileContent: id => id === 1 ? old.promise : current.promise })
  const first = store.openSkill({ id: 1 })
  await Promise.resolve()
  const second = store.openSkill({ id: 2 })
  current.resolve({ data: { content: 'Synthetic second skill' } }); assert.equal(await second, true)
  old.resolve({ data: { content: 'Synthetic first skill' } }); assert.equal(await first, false)
  assert.equal(store.currentSkill.id, 2); assert.equal(store.currentContent, 'Synthetic second skill')
  store.$dispose()
})

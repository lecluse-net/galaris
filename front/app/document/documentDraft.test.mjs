import assert from 'node:assert/strict'
import test from 'node:test'
import { documentDraftKey, restoreDocumentDraft, sameDocumentDraft } from './documentDraft.ts'

const draft = () => ({ owner: 'agent:7', title: 'Synthetic draft', content: '<p>Synthetic content</p>',
  keywords: ['one', 'two'], globalAccess: 0, sharing: { 7: 'edit', 8: 'read' } })
function storage() {
  const values = new Map()
  return { values, getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
}

test('draft comparisons preserve content and all editable metadata without depending on sharing key order', () => {
  const base = draft()
  assert.equal(sameDocumentDraft(base, structuredClone(base)), true)
  assert.equal(sameDocumentDraft(base, { ...base, sharing: { 8: 'read', 7: 'edit' } }), true)
  for (const change of [{ content: '<p>Changed content</p>' }, { title: 'Changed title' }, { owner: 'user:1' },
    { keywords: ['two', 'one'] }, { keywords: ['one'] }, { globalAccess: 2 }, { sharing: { 7: 'read', 8: 'read' } }, { sharing: { 7: 'edit' } }]) {
    assert.equal(sameDocumentDraft(base, { ...base, ...change }), false, JSON.stringify(change))
  }
  assert.equal(sameDocumentDraft(null, base), false)
})

test('draft recovery is isolated by human user, document and agent context', () => {
  const store = storage()
  const saved = { revision: 3, user_id: 1, base: draft(), draft: { ...draft(), content: '<p>Unsaved content</p>' } }
  const key = documentDraftKey(1, 7, 'doc')
  store.setItem(key, JSON.stringify(saved))
  assert.deepEqual(restoreDocumentDraft(store, 1, 7, 'doc'), saved)
  assert.equal(restoreDocumentDraft(store, 2, 7, 'doc'), null)
  assert.equal(restoreDocumentDraft(store, 1, null, 'doc'), null)
  assert.equal(restoreDocumentDraft(store, 1, 7, 'other'), null)
  // An explicitly mismatched envelope is never accepted even under the right key.
  store.setItem(key, JSON.stringify({ ...saved, user_id: 2 }))
  assert.equal(restoreDocumentDraft(store, 1, 7, 'doc'), null)
})

test('only attributed legacy drafts migrate and a failed migration keeps the original bytes', () => {
  const store = storage(), legacyKey = 'galaris:document-draft:7:doc'
  const saved = { revision: 3, base: draft(), draft: draft() }
  const unattributed = JSON.stringify(saved)
  store.setItem(legacyKey, unattributed)
  assert.equal(restoreDocumentDraft(store, 1, 7, 'doc'), null)
  assert.equal(store.getItem(legacyKey), unattributed)
  const attributed = JSON.stringify({ ...saved, user_id: 1 })
  store.setItem(legacyKey, attributed)
  assert.equal(restoreDocumentDraft(store, 2, 7, 'doc'), null)
  assert.throws(() => restoreDocumentDraft({ ...store, setItem() { throw Error('Synthetic quota failure') } }, 1, 7, 'doc'), /quota/)
  assert.equal(store.getItem(legacyKey), attributed)
  assert.deepEqual(restoreDocumentDraft(store, 1, 7, 'doc'), { ...saved, user_id: 1 })
  assert.equal(store.getItem(legacyKey), null)
  assert.equal(store.getItem(documentDraftKey(1, 7, 'doc')), attributed)
})

import assert from 'node:assert/strict'
import test from 'node:test'

import { excludeMemorySearchResults } from './searchResults.ts'


test('deleted memories are removed from displayed search results', () => {
  const results = [
    { id: 'kept-memory', title: 'Kept memory' },
    { id: 'deleted-memory', title: 'Deleted memory' },
  ]

  assert.deepEqual(
    excludeMemorySearchResults(results, new Set(['deleted-memory'])),
    [{ id: 'kept-memory', title: 'Kept memory' }],
  )
})


test('a stale search response cannot restore a deleted memory', () => {
  const deletedItemIds = new Set(['deleted-memory'])
  const staleResponse = [{ id: 'deleted-memory', title: 'Deleted memory' }]

  assert.deepEqual(excludeMemorySearchResults(staleResponse, deletedItemIds), [])
})

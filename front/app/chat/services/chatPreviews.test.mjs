import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../../test-support/load-typescript.mjs'
import { sessionReadCache } from '../../../test-support/session-read-cache.mjs'

function service(get) {
  return loadTypescript(new URL('./chatService.ts', import.meta.url), {
    '@/core/api': { api: { get }, AUTH_TOKEN_CHANGED_EVENT: 'auth' },
    '@/core/util/facade': sessionReadCache(), axios: { isAxiosError: () => false },
  }).chatService
}

test('preview reads share requests, isolate editable results and scope rooms, messages and viewers', async () => {
  const reads = []
  const api = service(async (url, options) => {
    reads.push([url, options.params.agent_id])
    return { data: [{ uri: 'https://example.test', title: 'Synthetic resource', metadata: { revision: 1 } }] }
  })
  const [one, two] = await Promise.all([api.messagePreviews('room', 'message'), api.messagePreviews('room', 'message')])
  one[0].metadata.revision = 9
  assert.equal(two[0].metadata.revision, 1)
  assert.equal((await api.messagePreviews('room', 'message'))[0].metadata.revision, 1)
  assert.equal(reads.length, 1)
  await api.messagePreviews('other-room', 'message')
  await api.messagePreviews('room', 'other-message')
  await api.messagePreviews('room', 'message', 7)
  assert.equal(reads.length, 4)
  api.invalidateMessagePreviews()
  await api.messagePreviews('room', 'message')
  assert.equal(reads.length, 5)
})

test('a shared capture refreshes enriched metadata once and leaves content downloads independent', async () => {
  let metadataReads = 0, imageReads = 0, contentReads = 0, captured = false
  const api = service(async url => {
    if (url.endsWith('/image')) { imageReads++; captured = true; return { data: new Blob(['image'], { type: 'image/png' }) } }
    if (url.endsWith('/content')) { contentReads++; return { data: new Blob(['original']) } }
    metadataReads++
    return { data: [{ uri: 'https://example.test', description: captured ? 'Captured description' : '' }] }
  })
  await api.messagePreviews('room', 'message')
  await Promise.all(Array.from({ length: 3 }, () => api.messagePreviewImageBlob('room', 'message', 'https://example.test', null, undefined, 'image', true)))
  const copies = await Promise.all(Array.from({ length: 3 }, () => api.messagePreviews('room', 'message')))
  assert.equal(imageReads, 1)
  assert.equal(metadataReads, 2)
  assert.ok(copies.every(items => items[0].description === 'Captured description'))
  await api.messagePreviewContentBlob('room', 'message', 'https://example.test')
  await api.messagePreviewContentBlob('room', 'message', 'https://example.test')
  assert.equal(contentReads, 2)
})

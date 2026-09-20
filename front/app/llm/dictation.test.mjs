import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

const { transcriptSuffix } = loadTypescript(new URL('./dictation.ts', import.meta.url), {})

test('live transcription keeps only new speech across repeated snapshots and punctuation revisions', () => {
  for (const [previous, next, addition] of [
    ['', 'Bonjour', 'Bonjour'],
    ['Bonjour', 'Bonjour', ''],
    ['Bonjour', '', ''],
    ['Bonjour.', 'bonjour !', ''],
    ['Bonjour.', 'Bonjour à tous.', 'à tous.'],
    ['spoken words', 'Spoken words, and more.', 'and more.'],
    ['bonjour', 'Bonjour bonjour', 'bonjour'],
    ['Un très beau jardin', 'Le très beau jardin fleurit.', 'fleurit.'],
  ]) assert.equal(transcriptSuffix(previous, next), addition, next)
})

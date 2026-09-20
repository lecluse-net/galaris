import assert from 'node:assert/strict'
import test from 'node:test'
import { visibleMessageText } from './messageDirectives.ts'

test('Task controls are removed from displayed messages, including the former @eff residue', () => {
  assert.equal(
    visibleMessageText('@task @effort Analyse ce rapport'),
    'Analyse ce rapport',
  )
  assert.equal(
    visibleMessageText('@eff @effort Analyse ce rapport'),
    'Analyse ce rapport',
  )
})

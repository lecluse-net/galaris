import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

const { groupMemberOptions: groupAgentOptions } = loadTypescript(new URL('./groupMemberOptions.ts', import.meta.url))

test('team sections preserve candidate identities, neutral choices, disabled state and multiple memberships', () => {
  const alpha = { id: 2, name: 'Research', order: 1 }, beta = { id: 1, name: 'Support', order: 2 }
  const options = [{ value: 8, label: 'Bob', disable: true }, { value: null, label: 'Everyone' },
    { value: 7, label: 'Alice', caption: 'Lead' }, { value: 9, label: 'Charlie' }]
  const agents = [{ id: 7, teams: [beta, alpha] }, { id: 8, teams: [beta] }, { id: 9, teams: [] },
    { id: 10, teams: [alpha] }]
  assert.deepEqual(groupAgentOptions(options, agents, 'No team'), [
    options[1], { ...options[2], teamHeading: 'Research' }, { ...options[0], teamHeading: 'Support' },
    options[2], { ...options[3], teamHeading: 'No team' },
  ])
  assert.deepEqual(options[2], { value: 7, label: 'Alice', caption: 'Lead' })
})

test('unavailable grouping metadata preserves consumer choices without assigning an unknown team', () => {
  const options = [{ value: null, label: 'Default' }, { value: 7, label: 'Alice' }, { value: 8, label: 'Bob' }]
  for (const metadata of [[], [{ id: 7, teams: [] }], [{ id: 8, teams: [] }]]) {
    assert.deepEqual(groupAgentOptions(options, metadata, 'No team'), options)
  }
})

import assert from 'node:assert/strict'
import test from 'node:test'

import { resourceTarget } from './presentation.ts'

test('native Process and run references open their own detail with the selected agent scope', () => {
  const id = '11111111-1111-4111-8111-111111111111'
  const entry = { uri: `galaris://processes/runs/${id}`, name: 'Synthetic execution' }
  assert.deepEqual(resourceTarget(entry, 7), {
    kind: 'process_run', id, title: entry.name, agentId: 7,
  })
  for (const suffix of ['/data', '/attachments/', `/attachments/${id}`]) {
    assert.equal(resourceTarget({ ...entry, uri: entry.uri + suffix }, 7), null)
  }
  const definition = { uri: 'galaris://processes/synthetic_process', name: 'process.json', metadata: { label: 'Synthetic process', tool_code: 'galaris' } }
  assert.deepEqual(resourceTarget(definition, 7), { kind: 'process', id: 'synthetic_process', title: 'Synthetic process', agentId: 7 })
  assert.equal(resourceTarget({ ...definition, uri: 'galaris://process/synthetic_process', metadata: { tool_code: 'n8n' } }, 7), null)
})

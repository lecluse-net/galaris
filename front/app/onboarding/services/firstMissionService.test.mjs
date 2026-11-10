import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../../test-support/load-typescript.mjs'

test('first mission keeps active recipients and repeats their identity within each team section', async () => {
  const research = { id: 2, name: 'Research', order: 1 }, support = { id: 1, name: 'Support', order: 2 }
  const recipients = [{ agent_id: 7, display_name: 'Alice', active: true }, { agent_id: 8, display_name: 'Bob', active: false },
    { agent_id: 9, display_name: 'Charlie', active: true }]
  let unavailable = false
  const { firstMissionService } = loadTypescript(new URL('./firstMissionService.ts', import.meta.url), {
    '@/core/api': { __esModule: true, default: { get: async url => {
      if (url === '/chat/status') return { data: { enabled: true, chat_enabled: true } }
      if (url === '/chat/recipients') return { data: { agents: recipients } }
      if (unavailable) throw Error('offline')
      assert.equal(url, '/agents/selection')
      return { data: [{ id: 7, teams: [support, research] }, { id: 8, teams: [support] }, { id: 9, teams: [] }] }
    } } },
  })
  const signal = new AbortController().signal
  assert.deepEqual(await firstMissionService.agents(signal), [
    { ...recipients[0], team_heading: 'Research' }, { ...recipients[0], team_heading: 'Support' },
    { ...recipients[2], without_team: true },
  ])
  unavailable = true
  assert.deepEqual(await firstMissionService.agents(signal), [recipients[0], recipients[2]])
})

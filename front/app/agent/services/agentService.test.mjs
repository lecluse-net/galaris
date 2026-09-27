import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../../test-support/load-typescript.mjs'
import { sessionReadCache } from '../../../test-support/session-read-cache.mjs'

function service(get) {
  return loadTypescript(new URL('./agentService.ts', import.meta.url), {
    '@/core/api': { __esModule: true, default: { get } }, '@/core/util/facade': sessionReadCache(),
  }).agentService
}

test('agent trees receive every page, including the agent after 500', async () => {
  const requests = []
  const agents = Array.from({ length: 501 }, (_, id) => ({ id }))
  const api = service(async (url, { params }) => {
    requests.push({ url, ...params })
    return { data: agents.slice(params.skip, params.skip + params.limit), status: 200 }
  })
  const result = await api.getAgents()
  assert.deepEqual(result.data, agents)
  assert.deepEqual(requests.map(item => item.skip), [0, 500])
})

test('a failed later page does not silently return an incomplete agent tree', async () => {
  const api = service(async (_url, { params }) => {
    if (params.skip) throw new Error('offline')
    return { data: Array.from({ length: 500 }, (_, id) => ({ id })) }
  })
  await assert.rejects(api.getAgents(), /offline/)
})

test('catalogues expire independently, isolate edits and invalidate after successful domain writes', async t => {
  t.mock.timers.enable({ apis: ['Date'], now: 0 })
  const reads = []
  let forbidden = false
  const http = {
    get: async url => { reads.push(url); return { data: [{ id: 7, title: { label: 'Synthetic' } }] } },
    post: async () => ({ data: { id: 8 } }),
    put: async () => { if (forbidden) throw Error('forbidden'); return { data: { id: 7 } } },
    delete: async () => ({ data: undefined }),
  }
  const { agentService: agents, titleService: titles, agentGroupService: groups } = loadTypescript(new URL('./agentService.ts', import.meta.url), {
    '@/core/api': { __esModule: true, default: http }, '@/core/util/facade': sessionReadCache(),
  })
  const first = await agents.getAgents()
  first.data[0].title.label = 'Local draft'
  assert.equal((await agents.getAgents()).data[0].title.label, 'Synthetic')
  await titles.getTitles()
  await groups.getGroups()
  await titles.getTitles()
  assert.equal(reads.length, 3)
  t.mock.timers.tick(60_001)
  await agents.getAgents()
  await titles.getTitles()
  assert.equal(reads.length, 4)
  await titles.updateTitle(7, { label: 'Saved' })
  await titles.getTitles()
  await agents.getAgents()
  assert.equal(reads.length, 6, 'embedded titles are invalidated too')
  forbidden = true
  await assert.rejects(agents.updateAgent(7, {}), /forbidden/)
  await agents.getAgents()
  assert.equal(reads.length, 6, 'failed writes leave valid data reusable')
  await groups.deleteGroup(7)
  await groups.getGroups()
  await agents.getAgents()
  assert.equal(reads.length, 8, 'detached group memberships are refreshed')
  t.mock.timers.tick(300_001)
  await titles.getTitles()
  assert.equal(reads.length, 9)
})

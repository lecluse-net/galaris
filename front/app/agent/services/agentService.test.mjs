import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

const output = ts.transpileModule(readFileSync(new URL('./agentService.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

function service(get) {
  const loaded = { exports: {} }
  new Function('require', 'module', 'exports', output)(() => ({ __esModule: true, default: { get } }), loaded, loaded.exports)
  return loaded.exports.agentService
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

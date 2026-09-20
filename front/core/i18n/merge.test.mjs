import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import ts from 'typescript'

const source = readFileSync(new URL('./merge.ts', import.meta.url), 'utf8')
const output = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText
const loaded = { exports: {} }
new Function('module', 'exports', output)(loaded, loaded.exports)
const { deepMergeMessages } = loaded.exports

test('locale merges do not share nested objects between languages', () => {
  const moduleEnglish = {
    nav: { agents: 'Agents' },
    steps: [{ label: 'English step' }],
  }
  const english = deepMergeMessages({}, moduleEnglish)
  const chinese = deepMergeMessages({}, moduleEnglish)

  deepMergeMessages(chinese, {
    nav: { agents: '智能体' },
    steps: [{ label: '中文步骤' }],
  })

  assert.equal(english.nav.agents, 'Agents')
  assert.equal(english.steps[0].label, 'English step')
  assert.equal(chinese.nav.agents, '智能体')
  assert.equal(chinese.steps[0].label, '中文步骤')
})

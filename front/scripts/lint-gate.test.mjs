import assert from 'node:assert/strict'
import test from 'node:test'
import { ESLint } from 'eslint'

const eslint = new ESLint()

test('lint covers TypeScript in each layer and rejects duplicated enum values', async () => {
  for (const layer of ['core', 'app', 'bridge']) {
    const [result] = await eslint.lintText('enum State { Pending = 1, Running = 1 }', { filePath: `${layer}/lint-canary.ts` })
    assert.ok(result.messages.some(m => m.ruleId === '@typescript-eslint/no-duplicate-enum-values'), layer)
  }
})

test('Vue template errors are blocked, while file-based route names are valid', async () => {
  const [bad] = await eslint.lintText('<template><div v-if="ok" v-else /></template>', { filePath: 'app/example/pages/index.vue' })
  assert.ok(bad.errorCount > 0)
  const [good] = await eslint.lintText('<template><div /></template>', { filePath: 'app/example/pages/index.vue' })
  assert.equal(good.errorCount, 0)
})

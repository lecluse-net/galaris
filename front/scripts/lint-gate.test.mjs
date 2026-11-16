import assert from 'node:assert/strict'
import test from 'node:test'
import { ESLint } from 'eslint'

// Synthetic files exercise syntax rules; the application lint checks real projects.
const eslint = new ESLint({ overrideConfig: [{ languageOptions: { parserOptions: { projectService: false } }, rules: { '@typescript-eslint/no-floating-promises': 'off', '@typescript-eslint/no-misused-promises': 'off' } }] })

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

test('application TypeScript and Vue callbacks reject unobserved promises', async () => {
  const typed = new ESLint()
  const [script] = await typed.lintText('async function run() {}\nrun()\nsetTimeout(async () => {}, 1)', { filePath: 'core/util/sessionStore.ts' })
  assert.ok(script.messages.some(message => message.ruleId === '@typescript-eslint/no-floating-promises'))
  assert.ok(script.messages.some(message => message.ruleId === '@typescript-eslint/no-misused-promises'))
  const [component] = await typed.lintText('<template><div /></template><script setup lang="ts">async function run() {}\nrun()</script>', { filePath: 'app/topic/components/TopicFormDialog.vue' })
  assert.ok(component.messages.some(message => message.ruleId === '@typescript-eslint/no-floating-promises'))
})

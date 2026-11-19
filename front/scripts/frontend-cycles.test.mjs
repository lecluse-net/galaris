import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { frontendEagerCycles } from './frontend-cycles.mjs'

function frontend(testContext, files) {
  const root = mkdtempSync(join(tmpdir(), 'frontend-cycles-'))
  testContext.after(() => rmSync(root, { recursive: true }))
  for (const [file, content] of Object.entries(files)) {
    const path = join(root, 'front', file)
    mkdirSync(dirname(path), { recursive: true })
    writeFileSync(path, content)
  }
  return join(root, 'front')
}

test('reports a same-domain Vue component that imports the barrel that exports it', t => {
  const root = frontend(t, {
    'core/navigation/index.ts': "export { default as Menu } from './Menu.vue'",
    'core/navigation/Menu.vue': '<template><nav /></template>\n<script setup lang="ts">\nimport { Menu } from "./"\n</script>',
  })
  assert.deepEqual(frontendEagerCycles(root), [[
    'front/core/navigation/Menu.vue', 'front/core/navigation/index.ts', 'front/core/navigation/Menu.vue',
  ]])
})

test('reports an eager contribution cycle and honors negative glob patterns', t => {
  const root = frontend(t, {
    'core/params/index.ts': [
      'export const contributors = import.meta.glob<unknown>([',
      "'../../app/*/{settings,setup}.ts', '!../../app/legacy/setup.ts',",
      '], { eager: true })',
    ].join('\n'),
    'app/harnesses/settings.ts': "export { contributors } from '@/core/params'",
    'app/legacy/setup.ts': "export { contributors } from '@/core/params'",
  })
  assert.deepEqual(frontendEagerCycles(root), [[
    'front/app/harnesses/settings.ts', 'front/core/params/index.ts', 'front/app/harnesses/settings.ts',
  ]])
})

test('ignores lazy imports, type-only bindings, raw globs, and commented Vue scripts', t => {
  const root = frontend(t, {
    'core/util/index.ts': "export { View } from '@/app/view'",
    'app/view/index.ts': [
      "import { type Example } from '@/core/util'",
      "export type * from '@/core/util'",
      "export const View = import('@/core/util')",
      "export const modules = import.meta.glob('../../core/util/*.ts')",
      "export const text = import.meta.glob('../../core/util/*.ts', { eager: true, query: '?raw' })",
      "export { default as Panel } from './Panel.vue'",
    ].join('\n'),
    'app/view/Panel.vue': '<!--\n<script setup>\nimport "../view"\n</script>\n-->\n<template><div /></template>',
  })
  assert.deepEqual(frontendEagerCycles(root), [])
})

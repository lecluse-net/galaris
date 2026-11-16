import assert from 'node:assert/strict'
import test from 'node:test'
import { ESLint } from 'eslint'

test('shared UI contracts reject inaccessible icons, blocking dialogs and unbounded action styles', async () => {
  const eslint = new ESLint({ overrideConfig: [{ files: ['**/*.vue'], languageOptions: { parserOptions: { projectService: false } }, rules: { '@typescript-eslint/no-floating-promises': 'off', '@typescript-eslint/no-misused-promises': 'off' } }] })
  const lint = async template => (await eslint.lintText(`<template>${template}</template><script setup lang="ts"></script>`, { filePath: 'app/index/components/UiContract.vue' }))[0].messages
  const invalid = await lint('<q-dialog persistent><q-btn flat color="negative" label="Delete" /><q-btn icon="edit" /><q-icon color="deep-purple-7" /></q-dialog>')
  assert.deepEqual(invalid.filter(message => message.ruleId === 'galaris/ui-conventions').map(message => message.messageId).sort(),
    ['deletion', 'dialogDismissal', 'labeledFlat', 'missingName', 'palette'])
  const valid = await lint('<q-dialog><q-btn color="negative" label="Delete" /><q-btn flat icon="edit" aria-label="Edit" /><q-icon color="solaire-iris" /></q-dialog>')
  assert.deepEqual(valid.filter(message => message.ruleId === 'galaris/ui-conventions'), [])
})

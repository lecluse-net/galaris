import assert from 'node:assert/strict'
import test from 'node:test'

import { compareFileEntries, resourceTarget, resourceLabel, isSkillPackage } from './presentation.ts'
import messages from './i18n.ts'

test('repository references open the code editor with their path and selected agent', () => {
  const id = '11111111-1111-4111-8111-111111111111'
  const entry = { uri: `galaris://code/${id}`, name: `code-${id}.json`, metadata: { label: 'work/project' } }
  assert.deepEqual(resourceTarget(entry, 7), { kind: 'code', id, title: 'work/project', agentId: 7 })
  for (const uri of ['galaris://code/', `${entry.uri}/`, `${entry.uri}/source.py`]) {
    assert.equal(resourceTarget({ ...entry, uri }, 7), null)
  }
})

test('system label codes use the selected locale while custom names and unknown codes keep their fallback', () => {
  const translate = locale => key => messages[locale].files.resourceLabels[key.split('.').at(-1)] ?? key
  const resource = { label_code: 'collection_task', name: 'Tasks' }
  assert.equal(resourceLabel(resource, translate('fr')), 'Tâches')
  assert.equal(resourceLabel(resource, translate('en')), 'Tasks')
  assert.equal(resourceLabel({ label_code: 'scheme_galaris' }, translate('fr')), 'Ressources Galaris')
  assert.equal(resourceLabel({ name: 'Tasks' }, translate('fr')), null)
  assert.equal(resourceLabel({ label_code: 'future_provider' }, translate('fr')), null)
})

test('only skill packages open a skill modal, leaving library branches and files navigable', () => {
  for (const uri of ['galaris://skill/sample/', 'galaris://skill/personnal/7/private-guide/']) {
    assert.equal(isSkillPackage({ uri, is_collection: true }), true)
    assert.equal(isSkillPackage({ uri, is_collection: false }), false)
  }
  for (const uri of ['galaris://skill/', 'galaris://skill/_category-1/', 'galaris://skill/_uncategorized/',
    'galaris://skill/personnal/', 'galaris://skill/personnal',
    'galaris://skill/personnal/7/', 'galaris://skill/sample/SKILL.md', 'galaris://skill/sample/references/',
    'galaris://skill/personnal/7/private-guide/references/']) {
    assert.equal(isSkillPackage({ uri, is_collection: true }), false)
  }
})

test('virtual collections retain the Goal before cycles and sort cycles by their numeric sequence', () => {
  const entry = (name, order) => ({ name, is_collection: false, metadata: { sort_order: order } })
  const goal = entry('Synthetic goal', 0)
  const cycles = [entry('10000', 10000), entry('0002', 2), entry('0001', 1)]
  assert.deepEqual([...cycles, goal].sort((a, b) => compareFileEntries(a, b, 'en')), [goal, cycles[2], cycles[1], cycles[0]])
  const ordinary = ['B.txt', 'A.txt'].map(name => ({ name, is_collection: false }))
  const folder = { name: 'Z', is_collection: true }
  assert.deepEqual([...ordinary, folder].sort((a, b) => compareFileEntries(a, b, 'en')), [folder, ordinary[1], ordinary[0]])
})

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

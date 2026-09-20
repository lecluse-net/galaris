import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'
import { privileges } from '../../core/authorize/definitions.ts'

const access = loadTypescript(new URL('./access.ts', import.meta.url), { '@/core/authorize': { privileges } })
const presentation = loadTypescript(new URL('./presentation.ts', import.meta.url), {})
const navigation = loadTypescript(new URL('./navigation.ts', import.meta.url), { './presentation': presentation, './access': access }).default
const incidentNavigation = loadTypescript(new URL('../incident/navigation.ts', import.meta.url), { '@/core/authorize': { privileges } }).default

const labKeys = [
  'tasks',
  'dispatcher',
  'briefing',
  'planner',
  'topic_classification',
  'memory_extraction',
  'outcome_reflection',
  'goal_tracking',
  'task_executor',
  'conversation_executor',
  'voice_executor',
]

test('each Lab section permits its reader or editor and rejects unrelated privileges', () => {
  assert.deepEqual(Object.keys(access.labSectionPrivileges).sort(), [...labKeys].sort())
  for (const key of labKeys) {
    const required = access.labSectionPrivileges[key]
    assert.equal(required.length, 2)
    for (const grant of required) {
      assert.equal(typeof grant, 'string')
      assert.equal(access.hasAnyPrivilege(value => value === grant, required), true)
    }
    assert.equal(access.hasAnyPrivilege(() => false, required), false)
    assert.equal(access.hasAnyPrivilege(value => value === privileges.INCIDENT_ACCESS, required), false)
  }
})

test('section grants open their own navigation entry without granting access to other sections', () => {
  const lab = navigation.admin.children.lab
  for (const section of presentation.labSections) {
    const grant = access.labSectionPrivileges[section.key][0]
    const has = value => value === grant
    assert.equal(access.hasAnyPrivilege(has, lab.privileges), true)
    const visible = Object.values(lab.children).filter(item => access.hasAnyPrivilege(has, item.privileges))
    assert.deepEqual(visible.map(item => item.to), [`/lab/${section.slug}`])
  }
})

test('the failure journal grants no Lab access and appears under monitoring', () => {
  const journal = incidentNavigation.monitor.children.incidents
  assert.equal(journal.to, '/incident')
  for (const grant of [privileges.INCIDENT_ACCESS, privileges.INCIDENT_EDIT]) {
    const has = value => value === grant
    assert.equal(access.hasAnyPrivilege(has, journal.privileges), true)
    assert.equal(access.hasAnyPrivilege(has, navigation.admin.children.lab.privileges), false)
  }
})

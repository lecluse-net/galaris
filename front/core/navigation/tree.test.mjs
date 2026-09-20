import assert from 'node:assert/strict'
import test from 'node:test'

import { mergeNavigationTrees } from './tree.ts'

function harnessNavigation(children = undefined) {
  return {
    admin: {
      children: {
        params: {
          children: {
            harnesses: {
              ...(children ? { children } : {}),
            },
          },
        },
      },
    },
  }
}

test('successive navigation merges do not retain provisional Harness entries', () => {
  const preferences = harnessNavigation()
  const provisional = harnessNavigation({
    harness_hermes: { label: 'Hermes', to: '/harnesses/bridge-hermes' },
  })
  const catalogue = harnessNavigation({
    harness_d8f1: { label: 'Hermes', to: '/harnesses/d8f1' },
  })

  const firstRender = {}
  mergeNavigationTrees(firstRender, preferences)
  mergeNavigationTrees(firstRender, provisional)

  const secondRender = {}
  mergeNavigationTrees(secondRender, preferences)
  mergeNavigationTrees(secondRender, catalogue)

  const preferencesHarnesses = preferences.admin.children.params.children.harnesses
  const renderedHarnesses = secondRender.admin.children.params.children.harnesses.children
  assert.equal(preferencesHarnesses.children, undefined)
  assert.deepEqual(Object.keys(renderedHarnesses), ['harness_d8f1'])
  assert.equal(renderedHarnesses.harness_d8f1.to, '/harnesses/d8f1')
})

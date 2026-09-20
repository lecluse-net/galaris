import assert from 'node:assert/strict'
import test from 'node:test'

import chatMessages from '../chat/i18n.ts'
import dreamMessages from '../dream/i18n.ts'
import indexMessages from '../index/i18n.ts'
import labMessages from '../lab/i18n.ts'
import llmMessages from '../llm/i18n.ts'
import onboardingMessages from '../onboarding/i18n.ts'
import hermesMessages from '../../bridge/hermes/i18n.ts'
import paramsMessages from '../../core/params/i18n.ts'
import skillMessages from './i18n.ts'

function stringValues(value) {
  if (typeof value === 'string') return [value]
  if (!value || typeof value !== 'object') return []
  return Object.values(value).flatMap(stringValues)
}

test('French user-facing catalogs call skills compétences except the technical introduction', () => {
  const catalogs = [
    chatMessages,
    dreamMessages,
    indexMessages,
    labMessages,
    llmMessages,
    onboardingMessages,
    hermesMessages,
    paramsMessages,
    skillMessages,
  ]

  for (const catalog of catalogs) {
    // Only this explanation names the standard Agent Skills format. Navigation,
    // controls and all other descriptions retain the French term compétences.
    const messages = catalog === skillMessages
      ? { ...catalog.fr, contextHelpPages: { ...catalog.fr.contextHelpPages, skills: undefined } }
      : catalog.fr
    for (const message of stringValues(messages)) {
      assert.doesNotMatch(message, /\bskills?\b/i)
    }
  }

  assert.equal(skillMessages.fr.nav.skills_desc, 'Bibliothèque de compétences pour les agents')
})

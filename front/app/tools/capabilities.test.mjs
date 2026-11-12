import assert from 'node:assert/strict'
import test from 'node:test'
import { loadTypescript } from '../../test-support/load-typescript.mjs'

const { capabilityLabels, toolCapabilitySelections } = loadTypescript(new URL('./capabilities.ts', import.meta.url), {})

test('standard labels are translated and extension labels stay literal', () => {
  const definitions = [{ code: 'mcp', label: 'standard.mcp', builtin: true,
    protocols: [{ value: 'http.mcp', label: 'standard.http', builtin: true }] },
  { code: 'sensors', label: 'Vendor sensors', builtin: false,
    protocols: [{ value: 'vendor.sensors', label: 'Vendor protocol', builtin: false }] }]
  const calls = []
  const t = (key, args) => { calls.push(key); return args ? `${args.capability} / ${args.protocol}` : `translated:${key}` }
  assert.equal(capabilityLabels('http.mcp', definitions, t).label, 'translated:standard.mcp / translated:standard.http')
  assert.equal(capabilityLabels('vendor.sensors', definitions, t).label, 'Vendor sensors / Vendor protocol')
  for (const value of ['unknown.sensors', 'Custom capability', 'tools.custom.external']) {
    assert.equal(capabilityLabels(value, definitions, t).label, value)
  }
  assert.deepEqual(calls, ['standard.mcp', 'standard.http', 'tools.capabilityProtocol', 'tools.capabilityProtocol'])
})

test('explicit selections stay intact while older Tool responses remain readable', () => {
  assert.deepEqual(toolCapabilitySelections({ capabilities: ['vendor.sensors'], has_mail: true }), ['vendor.sensors'])
  assert.deepEqual(toolCapabilitySelections({ capabilities: [], has_mail: true }), [])
  assert.deepEqual(toolCapabilitySelections({ mcp_config: { type: 'sse' }, has_mail: true, has_calendar: true }),
    ['sse.mcp', 'imap_smtp.mail', 'ical.calendar'])
})

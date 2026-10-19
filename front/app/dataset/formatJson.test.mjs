import test from 'node:test'
import assert from 'node:assert/strict'
import { formatJson } from './formatJson.ts'

test('indentation preserves numeric precision, key order and string escapes', () => {
  const source = '{"2":9007199254740993,"1":1.2300e+40,"literal":"{ \\" x\\n\\u00e9","empty":[{},[]],"values":[false,null,-0]}'
  const formatted = formatJson(source)
  assert.equal(formatted, '{\n  "2": 9007199254740993,\n  "1": 1.2300e+40,\n  "literal": "{ \\" x\\n\\u00e9",\n  "empty": [\n    {},\n    []\n  ],\n  "values": [\n    false,\n    null,\n    -0\n  ]\n}')
  assert.equal(formatJson(formatted), formatted)
})

test('all JSON roots format safely and invalid drafts remain untouched', () => {
  for (const source of ['0', '-0', 'true', 'false', 'null', '"hello world"', '{}', '[]']) {
    assert.equal(formatJson(`  ${source} \n`), source)
  }
  for (const draft of ['', '{', '{"incomplete": ', 'not JSON']) assert.equal(formatJson(draft), draft)
})
